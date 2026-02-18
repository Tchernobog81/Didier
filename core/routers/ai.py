import re
import os
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from orchestrator.openclaw_bridge import get_openclaw_bridge

router = APIRouter()


def _flag_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _asr_worker_enabled(orchestrator: Any) -> bool:
    return _flag_enabled(orchestrator.config.get("asr.worker_mode", False)) or _flag_enabled(
        os.getenv("DIDIER_ASR_WORKER_MODE", "0")
    )


async def _relay_asr_worker_wake_test(
    payload: dict[str, Any], orchestrator: Any
) -> dict[str, Any]:
    base_url = (
        str(
            orchestrator.config.get(
                "asr.worker_url", os.getenv("DIDIER_ASR_WORKER_URL", "http://127.0.0.1:5014")
            )
        )
        .strip()
        .rstrip("/")
    )
    timeout_s = max(3.0, min(float(payload.get("timeout_seconds", 12.0)) + 5.0, 40.0))
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(f"{base_url}/wake-test", json=payload)
        response.raise_for_status()
        data = response.json()
    return data if isinstance(data, dict) else {"status": "error", "detail": "invalid_response"}


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
    return normalized


def _matches_wake(transcript: str, wake_words: list[str]) -> bool:
    normalized = _normalize_text(transcript)
    compact = normalized.replace(" ", "")
    for wake in wake_words:
        wake_norm = _normalize_text(wake)
        if not wake_norm:
            continue
        if wake_norm in normalized:
            return True
        if wake_norm.replace(" ", "") in compact:
            return True
    tokens = normalized.split()
    has_yo = any(tok.startswith("yo") for tok in tokens)
    has_did = any(tok.startswith("didi") or tok.startswith("didie") for tok in tokens)
    if has_yo and has_did:
        return True
    has_y = any(tok.startswith("y") for tok in tokens)
    di_letters = sum(1 for tok in tokens if tok in {"d", "i"})
    if has_y and di_letters >= 3:
        return True
    if compact.startswith("ya") and "ddii" in compact:
        return True
    return False


def _latest_mic_transcript(since_ts: float) -> tuple[str, float, str | None]:
    latest_text = ""
    latest_ts = 0.0
    latest_file: str | None = None
    tmp_dir = Path("/tmp")
    try:
        candidates = sorted(
            tmp_dir.glob("didier_mic_*_mono.wav.txt"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
    except Exception:
        return latest_text, latest_ts, latest_file
    for path in candidates[:40]:
        try:
            ts = float(path.stat().st_mtime)
        except Exception:
            continue
        if ts < since_ts - 1.0:
            break
        try:
            text = path.read_text(encoding="utf-8").strip()
        except Exception:
            continue
        if text:
            latest_text = text
            latest_ts = ts
            latest_file = path.name
            break
    return latest_text, latest_ts, latest_file


async def _list_ollama_models(base_url: str) -> list[str]:
    url = f"{base_url.rstrip('/')}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=4) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return []
    models: list[str] = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if name:
            models.append(str(name))
    return models


def _model_size_b(model_name: str) -> float:
    match = re.search(r":(\d+(?:\.\d+)?)b\b", str(model_name).lower())
    if not match:
        return 999.0
    try:
        return float(match.group(1))
    except Exception:
        return 999.0


def _pick_model(available_models: list[str], candidates: list[str]) -> str | None:
    cleaned: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        value = str(candidate or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        cleaned.append(value)
    if available_models:
        for candidate in cleaned:
            if candidate in available_models:
                return candidate
        # Fallback safety: prefer the smallest installed model to avoid long latency spikes.
        return sorted(available_models, key=_model_size_b)[0]
    if cleaned:
        return cleaned[0]
    return None


def _is_listening_only_response(text: str) -> bool:
    normalized = _normalize_text(str(text or ""))
    return normalized in {
        "je t ecoute",
        "je vous ecoute",
        "jecoute",
        "j ecoute",
    }


def _parse_switch_action(prompt_norm: str) -> str | None:
    if any(
        token in prompt_norm
        for token in (
            "eteins",
            "eteindre",
            "eteint",
            "coupe",
            "arrete",
            "stop",
            "off",
        )
    ):
        return "off"
    if any(
        token in prompt_norm
        for token in (
            "allume",
            "allumer",
            "allum",
            "active",
            "demarre",
            "on",
        )
    ):
        return "on"
    return None


def _looks_like_vision_anomaly(prompt: str) -> bool:
    norm = _normalize_text(prompt)
    if "anomal" not in norm:
        return False
    return any(token in norm for token in ("vision", "camera", "flux", "detection", "detect"))


def _should_react_filter(
    payload: dict[str, Any], prompt: str, orchestrator: Any
) -> bool:
    if "react_filter" in payload:
        return bool(payload.get("react_filter"))
    if _looks_like_vision_anomaly(prompt):
        return bool(orchestrator.config.get("openclaw.anomaly_react_enabled", True))
    return bool(orchestrator.config.get("openclaw.react_filter_default", False))


async def _relay_openclaw_react(
    payload: dict[str, Any], prompt: str, orchestrator: Any, api_module: Any
) -> dict[str, Any] | None:
    if not _should_react_filter(payload, prompt, orchestrator):
        return None
    timeout_s = float(payload.get("react_timeout_s", 2.0))
    timeout_s = max(0.5, min(timeout_s, 8.0))
    wake_mode = str(payload.get("react_wake_mode", "now")).strip() or "now"
    agent_id = str(payload.get("react_agent_id", "")).strip() or None
    session_key = str(payload.get("react_session_key", "")).strip() or None

    def _call_bridge() -> dict[str, Any]:
        bridge = get_openclaw_bridge()
        return bridge.relay_prompt(
            prompt,
            agent_id=agent_id,
            session_key=session_key,
            wake_mode=wake_mode,
            timeout_s=timeout_s,
        )

    try:
        return await api_module.asyncio.to_thread(_call_bridge)
    except Exception as exc:
        return {"ok": False, "error": f"openclaw react relay failed: {exc}"}


def _metrics_from_openclaw(timeout_s: float) -> dict[str, Any]:
    bridge = get_openclaw_bridge()
    return bridge.metrics(timeout_s=timeout_s)


def _resolve_actuator_target(
    prompt_norm: str, devices: list[dict[str, Any]]
) -> tuple[str, str] | None:
    best_id = ""
    best_name = ""
    best_score = 0
    for device in devices:
        device_id = str(device.get("id", "")).strip()
        device_name = str(device.get("name", "")).strip()
        if not device_id or not device_name:
            continue
        name_norm = _normalize_text(device_name)
        if not name_norm:
            continue
        score = 0
        if name_norm in prompt_norm:
            score += len(name_norm) + 20
        for part in name_norm.split():
            if len(part) < 3:
                continue
            if part in prompt_norm:
                score += len(part)
        if score > best_score:
            best_score = score
            best_id = device_id
            best_name = device_name
    if best_score <= 0:
        return None
    return best_id, best_name


@router.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    orchestrator = api_module._require_orchestrator()
    vocal = orchestrator.get_tentacle("vocal")
    if not vocal:
        raise HTTPException(status_code=503, detail="vocal tentacle not loaded")
    await vocal.speak(text)
    return {"status": "queued"}


@router.post("/music/play")
async def music_play(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(payload.get("prompt", "")).strip() or "musique"
    orchestrator = api_module._require_orchestrator()
    music = orchestrator.get_tentacle("music")
    if not music:
        raise HTTPException(status_code=503, detail="music tentacle not loaded")
    await music.play(prompt)
    return {"status": "queued", "prompt": prompt}


@router.post("/audio/test")
async def audio_test() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    sink = orchestrator.config.get("bluetooth.sink_name", "")
    path = api_module.Path("data/soundboks_test.wav")
    try:
        import numpy as np

        sample_rate = 22050
        segments = [
            (0.12, 1.0),
            (0.08, 0.8),
            (0.12, 0.6),
        ]
        audio = np.zeros(0, dtype=np.float32)
        for duration, gain in segments:
            n = int(sample_rate * duration)
            t = np.linspace(0, duration, n, False)
            noise = np.random.uniform(-1, 1, n).astype(np.float32)
            tone = np.sin(2 * np.pi * (500 + 200 * np.exp(-t * 8)) * t).astype(
                np.float32
            )
            envelope = np.exp(-t * 12).astype(np.float32)
            bark = gain * envelope * (0.6 * noise + 0.4 * tone)
            audio = np.concatenate([audio, bark, np.zeros(int(sample_rate * 0.05))])
        audio = np.clip(audio, -1.0, 1.0)
        api_module.sf.write(str(path), audio, sample_rate)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to generate test audio")

    cmd = ["paplay"]
    if sink:
        cmd += ["-d", sink]
    cmd.append(str(path))
    try:
        await api_module.asyncio.to_thread(api_module.subprocess.run, cmd, check=True)
    except Exception:
        raise HTTPException(status_code=500, detail="paplay failed")
    return {"status": "played", "sink": sink}


@router.post("/ask")
async def ask(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = api_module._require_orchestrator()
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    ask_profile_model = orchestrator.config.get(
        "ollama.model_profiles.ask",
        orchestrator.config.get("ollama.ask_model", None),
    )
    default_model = orchestrator.config.get("ollama.model", None)
    available_models = await _list_ollama_models(base_url)
    clean_prompt, expert_model, expert_system, _expert = api_module._resolve_expert_prompt(
        prompt, orchestrator.config
    )
    react_result = await _relay_openclaw_react(
        payload=payload,
        prompt=clean_prompt,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    resolved_model = _pick_model(
        available_models, [expert_model, ask_profile_model, default_model]
    )
    if not resolved_model:
        raise HTTPException(status_code=503, detail="Ollama unavailable: no model configured")
    # Keep chat path low-latency: send a compact prompt to avoid long prefill stalls.
    full_prompt = f"Reponds en francais, brievement.\n{clean_prompt}"
    if expert_system:
        full_prompt = (
            f"Reponds en francais, brievement.\n{str(expert_system).strip()}\n\n{clean_prompt}"
        )
    ask_num_predict = int(orchestrator.config.get("ollama.ask_num_predict", 24))
    if ask_num_predict <= 0:
        ask_num_predict = 24
    ask_num_predict = min(ask_num_predict, 24)
    payload_data: dict[str, Any] = {
        "model": resolved_model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": ask_num_predict,
            "temperature": float(orchestrator.config.get("ollama.temperature", 0.4)),
        },
    }
    keep_alive = orchestrator.config.get("ollama.keep_alive", None)
    if keep_alive:
        payload_data["keep_alive"] = keep_alive
    timeout_s = float(orchestrator.config.get("ollama.timeout_seconds", 120))
    timeout_s = max(5.0, min(timeout_s, 25.0))
    url = f"{base_url}/api/generate"
    try:
        api_module.update_status(
            thinking=True,
            state="THINKING",
            last_prompt=clean_prompt,
            last_prompt_at=api_module.time.time(),
        )
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            ollama_response = await client.post(url, json=payload_data)
            ollama_response.raise_for_status()
            data = ollama_response.json()
        response = str(data.get("response", "")).strip()
        if not response:
            response = "Je t'ecoute."
        if _is_listening_only_response(response):
            response = "Salut. Dis-moi l'action precise que tu veux lancer."
        api_module.update_status(
            thinking=False,
            state="IDLE",
            last_response=response,
            last_response_at=api_module.time.time(),
        )
    except Exception as exc:
        api_module.update_status(thinking=False, state="IDLE", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    result: dict[str, Any] = {"response": response}
    if react_result is not None:
        result["react"] = react_result
    return result


@router.post("/agent/react")
async def agent_react(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = api_module._require_orchestrator()
    react_payload = dict(payload)
    react_payload["react_filter"] = True
    result = await _relay_openclaw_react(
        payload=react_payload,
        prompt=prompt,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    if result is None:
        result = {"ok": False, "error": "openclaw react relay skipped"}
    return result


@router.get("/agent/metrics")
async def agent_metrics(timeout_s: float = 4.0) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    timeout_s = max(0.5, min(float(timeout_s), 12.0))
    result = await api_module.asyncio.to_thread(_metrics_from_openclaw, timeout_s)
    if not result.get("ok", False):
        raise HTTPException(status_code=503, detail=result.get("error", "openclaw unavailable"))
    return result


@router.post("/coding")
async def coding(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = api_module._require_orchestrator()
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    coding_profile_model = orchestrator.config.get(
        "ollama.model_profiles.coding", None
    )
    model = orchestrator.config.get("coding.model", orchestrator.config.get("ollama.model"))
    available_models = await _list_ollama_models(base_url)
    resolved_model = _pick_model(
        available_models,
        [model, coding_profile_model, orchestrator.config.get("ollama.model", None)],
    )
    if not resolved_model:
        raise HTTPException(status_code=503, detail="Ollama unavailable: no model configured")
    num_predict = orchestrator.config.get("coding.num_predict", 400)
    temperature = orchestrator.config.get("coding.temperature", 0.2)
    system_prompt = orchestrator.config.get("coding.system_prompt", "").strip()

    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\nUser: {prompt}\nAssistant:"

    payload_data = {
        "model": resolved_model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    keep_alive = orchestrator.config.get("ollama.keep_alive", None)
    if keep_alive:
        payload_data["keep_alive"] = keep_alive
    url = f"{base_url}/api/generate"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return {"response": str(data.get("response", "")).strip()}


@router.get("/ollama/models")
async def ollama_models() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    url = f"{base_url}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return data


@router.get("/asr/status")
async def asr_status() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    return api_module._read_asr_status()


@router.post("/asr/wake-test")
async def asr_wake_test(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    payload = payload or {}
    orchestrator = api_module._require_orchestrator()
    if _asr_worker_enabled(orchestrator):
        try:
            return await _relay_asr_worker_wake_test(payload, orchestrator)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"ASR worker unavailable: {exc}")
    vocal = orchestrator.get_tentacle("vocal")
    hearing = orchestrator.get_tentacle("hearing")
    if not hearing:
        raise HTTPException(status_code=503, detail="hearing tentacle not loaded")
    if hasattr(hearing, "_enabled") and not getattr(hearing, "_enabled", True):
        raise HTTPException(status_code=503, detail="hearing tentacle disabled")

    inject_wake_tts = bool(payload.get("inject_wake_tts", True))
    loopback_tts_fallback = bool(payload.get("loopback_tts_fallback", True))
    reply_on_wake = bool(payload.get("reply_on_wake", True))
    needs_vocal = inject_wake_tts or loopback_tts_fallback or reply_on_wake
    if needs_vocal and not vocal:
        raise HTTPException(status_code=503, detail="vocal tentacle not loaded")
    if (
        needs_vocal
        and vocal is not None
        and hasattr(vocal, "_enabled")
        and not getattr(vocal, "_enabled", True)
    ):
        raise HTTPException(status_code=503, detail="vocal tentacle disabled")

    wake_word = str(orchestrator.config.get("asr.wake_word", "Yo! Didier")).strip()
    if not wake_word:
        wake_word = "Yo! Didier"
    aliases = orchestrator.config.get("asr.wake_word_aliases", []) or []
    wake_words = [wake_word] + [str(item).strip() for item in aliases if str(item).strip()]
    timeout_s = max(3.0, min(float(payload.get("timeout_seconds", 12.0)), 30.0))
    repeats = max(1, min(int(payload.get("repeats", 2)), 4))
    repeat_gap_s = max(0.2, min(float(payload.get("repeat_gap_seconds", 0.8)), 2.0))
    if not inject_wake_tts:
        loopback_tts_fallback = False
    wake_reply_text = str(
        payload.get(
            "wake_reply_text",
            orchestrator.config.get(
                "asr.wake_reply_text",
                "Salut Tcherno, qu'est-ce que je peux faire pour toi ?",
            ),
        )
    ).strip()
    playback_budget_s = max(4.0, repeats * 3.5) if inject_wake_tts else 0.0
    total_timeout_s = timeout_s + playback_budget_s

    before = api_module._read_asr_status()
    if not bool(before.get("listening", False)):
        raise HTTPException(status_code=503, detail="ASR loop inactive")
    baseline_ts = float(before.get("last_heard_at") or before.get("updated_at") or 0.0)
    baseline_transcript = str(before.get("last_transcript") or "")
    started_at = api_module.time.time()

    if inject_wake_tts and vocal is not None:
        for idx in range(repeats):
            await vocal.speak(wake_word)
            if idx < repeats - 1:
                await api_module.asyncio.sleep(repeat_gap_s)

    matched = False
    heard_transcript = ""
    heard_at = 0.0
    heard_file = None
    while api_module.time.time() - started_at <= total_timeout_s:
        await api_module.asyncio.sleep(0.25)
        status = api_module._read_asr_status()
        transcript = str(status.get("last_transcript") or "").strip()
        ts = float(status.get("last_heard_at") or status.get("updated_at") or 0.0)
        if transcript and ts > baseline_ts:
            heard_transcript = transcript
            heard_at = ts
            if _matches_wake(transcript, wake_words):
                matched = True
                break
        file_text, file_ts, file_name = _latest_mic_transcript(started_at)
        if file_text and file_ts > heard_at:
            heard_transcript = file_text
            heard_at = file_ts
            heard_file = file_name
            if _matches_wake(file_text, wake_words):
                matched = True
                break

    loopback_used = False
    if not matched and loopback_tts_fallback and vocal is not None:
        await vocal.speak(wake_word)
        await api_module.asyncio.sleep(0.8)
        output_path = Path(str(getattr(vocal, "_output_path", "")))
        match_method = getattr(hearing, "_matches_wake_word", None)
        wake_method = getattr(hearing, "_on_wake_word", None)
        wake_model_path = getattr(hearing, "_wake_model_path", None)
        whisper_bin = str(getattr(hearing, "_whisper_bin", "")).strip()
        language = str(getattr(hearing, "_language", "fr")).strip() or "fr"
        if (
            output_path
            and output_path.exists()
            and callable(match_method)
            and callable(wake_method)
            and whisper_bin
            and wake_model_path
        ):
            loopback_wav = Path(f"/tmp/didier_wake_loopback_{int(api_module.time.time() * 1000)}.wav")
            loopback_txt = loopback_wav.with_suffix(".wav.txt")
            try:
                if output_path.stat().st_size <= 0:
                    raise RuntimeError("empty tts output")
                loopback_wav.write_bytes(output_path.read_bytes())
                whisper_cmd = [
                    whisper_bin,
                    "-m",
                    str(wake_model_path),
                    "-f",
                    str(loopback_wav),
                    "-l",
                    language,
                    "-otxt",
                    "-np",
                    "-nt",
                    "-t",
                    "4",
                    "-bs",
                    "1",
                    "-bo",
                    "1",
                ]
                await api_module.asyncio.to_thread(
                    subprocess.run, whisper_cmd, check=False, capture_output=True
                )
                loop_text = (
                    loopback_txt.read_text(encoding="utf-8").strip()
                    if loopback_txt.exists()
                    else None
                )
            except Exception:
                loop_text = None
            finally:
                try:
                    if loopback_wav.exists():
                        loopback_wav.unlink()
                except Exception:
                    pass
                try:
                    if loopback_txt.exists():
                        loopback_txt.unlink()
                except Exception:
                    pass
            if loop_text:
                loopback_used = True
                heard_transcript = str(loop_text).strip()
                heard_at = api_module.time.time()
                heard_file = "tts_loopback"
                if bool(match_method(loop_text)):
                    matched = True
                    await wake_method(loop_text)

    wake_reply_queued = False
    if matched and reply_on_wake and wake_reply_text and vocal is not None:
        await vocal.speak(wake_reply_text)
        wake_reply_queued = True

    elapsed_s = round(api_module.time.time() - started_at, 2)
    final_status = api_module._read_asr_status()
    audio_detected = bool(str(heard_transcript).strip())
    status_value = "ok" if matched else ("audio_only" if audio_detected else "timeout")
    return {
        "status": status_value,
        "wake_word": wake_word,
        "wake_words": wake_words,
        "inject_wake_tts": inject_wake_tts,
        "timeout_seconds": timeout_s,
        "playback_budget_seconds": playback_budget_s,
        "total_timeout_seconds": total_timeout_s,
        "repeats": repeats,
        "elapsed_seconds": elapsed_s,
        "matched": matched,
        "audio_detected": audio_detected,
        "heard_transcript": heard_transcript,
        "heard_at": heard_at or None,
        "heard_file": heard_file,
        "loopback_used": loopback_used,
        "wake_reply_queued": wake_reply_queued,
        "wake_reply_text": wake_reply_text if wake_reply_queued else "",
        "baseline_transcript": baseline_transcript,
        "asr_state": final_status.get("state"),
        "listening": bool(final_status.get("listening", False)),
    }


@router.post("/ask-and-speak")
async def ask_and_speak(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = api_module._require_orchestrator()
    vocal = orchestrator.get_tentacle("vocal")
    music = orchestrator.get_tentacle("music")
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    ask_profile_model = orchestrator.config.get(
        "ollama.model_profiles.ask",
        orchestrator.config.get("ollama.ask_model", None),
    )
    default_model = orchestrator.config.get("ollama.model", None)
    available_models = await _list_ollama_models(base_url)
    clean_prompt, expert_model, expert_system, _expert = api_module._resolve_expert_prompt(
        prompt, orchestrator.config
    )
    react_result = await _relay_openclaw_react(
        payload=payload,
        prompt=clean_prompt,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    resolved_model = _pick_model(
        available_models, [expert_model, ask_profile_model, default_model]
    )
    prompt_norm = _normalize_text(clean_prompt)
    if any(
        key in prompt_norm
        for key in ("parle moi en francais", "reponds en francais", "en francais")
    ):
        response = "D'accord, je te reponds en francais."
        if vocal:
            await vocal.speak(response)
            result = {"response": response, "audio": True}
            if react_result is not None:
                result["react"] = react_result
            return result
        result = {"response": response, "audio": False}
        if react_result is not None:
            result["react"] = react_result
        return result

    actuators = orchestrator.get_tentacle("actuators")
    action = _parse_switch_action(prompt_norm)
    if actuators and action:
        try:
            devices = list(actuators.list_devices())
        except Exception:
            devices = []
        target = _resolve_actuator_target(prompt_norm, devices)
        if target:
            actuator_id, actuator_name = target
            try:
                result = await api_module.asyncio.to_thread(
                    actuators.command, actuator_id, action, {}
                )
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            ok = bool(result.get("ok", False))
            if ok:
                verb = "allumee" if action == "on" else "eteinte"
                response = f"{actuator_name} {verb}."
            else:
                response = (
                    f"Action impossible sur {actuator_name}: "
                    f"{result.get('error', 'erreur inconnue')}"
                )
            if vocal:
                await vocal.speak(response)
                result = {
                    "response": response,
                    "audio": True,
                    "actuator": {"id": actuator_id, "name": actuator_name, "action": action, "ok": ok},
                }
                if react_result is not None:
                    result["react"] = react_result
                return result
            result = {
                "response": response,
                "audio": False,
                "actuator": {"id": actuator_id, "name": actuator_name, "action": action, "ok": ok},
            }
            if react_result is not None:
                result["react"] = react_result
            return result

    if music and api_module._is_music_prompt(prompt):
        await music.play(prompt)
        response = "Musique lancée."
        if vocal:
            await vocal.speak(response)
        result = {"response": response, "audio": bool(vocal), "music": True}
        if react_result is not None:
            result["react"] = react_result
        return result
    if not resolved_model:
        raise HTTPException(status_code=503, detail="Ollama unavailable: no model configured")
    full_prompt = f"Reponds en francais, brievement.\n{clean_prompt}"
    if expert_system:
        full_prompt = (
            f"Reponds en francais, brievement.\n{str(expert_system).strip()}\n\n{clean_prompt}"
        )
    ask_num_predict = int(orchestrator.config.get("ollama.ask_num_predict", 24))
    if ask_num_predict <= 0:
        ask_num_predict = 24
    ask_num_predict = min(ask_num_predict, 24)
    payload_data: dict[str, Any] = {
        "model": resolved_model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": ask_num_predict,
            "temperature": float(orchestrator.config.get("ollama.temperature", 0.4)),
        },
    }
    keep_alive = orchestrator.config.get("ollama.keep_alive", None)
    if keep_alive:
        payload_data["keep_alive"] = keep_alive
    timeout_s = float(orchestrator.config.get("ollama.timeout_seconds", 120))
    timeout_s = max(5.0, min(timeout_s, 25.0))
    url = f"{base_url}/api/generate"
    try:
        api_module.update_status(
            thinking=True,
            state="THINKING",
            last_prompt=clean_prompt,
            last_prompt_at=api_module.time.time(),
        )
        async with httpx.AsyncClient(timeout=timeout_s) as client:
            ollama_response = await client.post(url, json=payload_data)
            ollama_response.raise_for_status()
            data = ollama_response.json()
        response = str(data.get("response", "")).strip()
        if not response:
            retry_payload: dict[str, Any] = {
                "model": resolved_model,
                "prompt": clean_prompt,
                "stream": False,
                "options": {
                    "num_predict": min(32, max(12, ask_num_predict)),
                    "temperature": float(orchestrator.config.get("ollama.temperature", 0.4)),
                },
            }
            async with httpx.AsyncClient(timeout=min(timeout_s, 15.0)) as client:
                retry_response = await client.post(url, json=retry_payload)
                retry_response.raise_for_status()
                retry_data = retry_response.json()
            response = str(retry_data.get("response", "")).strip()
        if not response:
            prompt_lower = clean_prompt.lower()
            if "salut" in prompt_lower or "bonjour" in prompt_lower:
                response = "Salut. Je suis pret, dis-moi quoi faire."
            else:
                response = "Je suis pret, donne-moi une action precise."
        if _is_listening_only_response(response):
            response = "Salut. Dis-moi l'action precise que tu veux lancer."
        api_module.update_status(
            thinking=False,
            last_response=response,
            last_response_at=api_module.time.time(),
        )
    except Exception as exc:
        api_module.update_status(thinking=False, state="IDLE", error=str(exc))
        response = "Je suis encore en charge. Reessaie dans quelques secondes."
    audio_ok = False
    if vocal:
        await vocal.speak(response)
        audio_ok = True
    else:
        api_module.update_status(state="IDLE")
    result = {"response": response, "audio": audio_ok}
    if react_result is not None:
        result["react"] = react_result
    return result
