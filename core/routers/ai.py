import asyncio
import re
import os
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException
from core.backend_routing import choose_backend as choose_backend_contract
from core.ollama_targeting import probe_ollama_endpoint
from core.ollama_targeting import resolve_pixel_ollama_base_url
from core.routers.guards import circuit_breaker
from core.resource_arbitrator import get_resource_arbitrator
from core.shared_state import read_state as read_shared_state
from shared.ipc import request as ipc_request

router = APIRouter()
DEFAULT_HTTP_TIMEOUT_S = 2.0
DEFAULT_SUBPROCESS_TIMEOUT_S = 2.0
_PICOBOT_DEFAULT_BASES = ("http://127.0.0.1:3901", "http://localhost:3901")
_OLLAMA_MODELS_CACHE_TTL_S = 5.0
_OLLAMA_MODELS_CACHE: dict[str, Any] | None = None
_OLLAMA_MODELS_CACHE_TS = 0.0
_OLLAMA_MODELS_LOCK = asyncio.Lock()


def _http_timeout(seconds: float | int) -> float:
    return max(0.1, min(float(seconds), DEFAULT_HTTP_TIMEOUT_S))


def _http_error_brief(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = "unknown"
        detail = ""
        if exc.response is not None:
            status = str(exc.response.status_code)
            try:
                detail = str(exc.response.text or "").strip().replace("\n", " ")
            except Exception:
                detail = ""
        return f"HTTPStatusError:{status}:{detail[:120]}"
    return f"{type(exc).__name__}"


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
    async with httpx.AsyncClient(timeout=_http_timeout(timeout_s)) as client:
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
        async with httpx.AsyncClient(timeout=_http_timeout(4)) as client:
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
        return bool(orchestrator.config.get("picobot.anomaly_react_enabled", True))
    return bool(
        orchestrator.config.get("picobot.react_filter_default", False)
    )


def _infer_task_type(
    prompt: str,
    payload: dict[str, Any],
    *,
    is_task: bool,
) -> str:
    explicit = str(payload.get("task_type", "")).strip()
    if explicit:
        return explicit
    if is_task:
        return "react_task"
    norm = _normalize_text(prompt)
    if any(token in norm for token in ("vision", "camera", "detection", "objet", "forme", "npu")):
        return "vision"
    return "chat"


def choose_backend(prompt: str, task_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = dict(payload or {})
    ctx["prompt_preview"] = str(prompt or "")[:120]
    ctx["voice_request"] = bool(ctx.get("is_voice", False))
    return choose_backend_contract(prompt, task_type, context=ctx)


async def _resolve_ollama_base_for_backend(
    *,
    orchestrator: Any,
    backend_choice: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    base_url = str(orchestrator.config.get("ollama.base_url", "http://localhost:11434")).strip().rstrip("/")
    routing = dict(backend_choice or {})
    execution_backend = str(routing.get("execution_backend", "local_ollama")).strip() or "local_ollama"
    if execution_backend != "pixel_ollama":
        return base_url, routing, []

    root_cfg = {
        "routing": orchestrator.config.get("routing", {}) or {},
        "hardware": {
            "discovery": {
                "pixel_ip_hints": orchestrator.config.get("hardware.discovery.pixel_ip_hints", []) or []
            }
        },
    }
    pixel_hint = str((payload or {}).get("pixel_ollama_url", "")).strip()
    pixel_base = pixel_hint or resolve_pixel_ollama_base_url(
        root_config=root_cfg,
        shared_state=read_shared_state(),
    )
    if not pixel_base:
        routing["execution_backend"] = "local_ollama"
        routing["fallback_active"] = True
        routing["fallback_reason"] = "pixel_ollama_url_unresolved"
        return base_url, routing, []

    health_timeout_s = float(orchestrator.config.get("routing.pixel_ollama.health_timeout_s", DEFAULT_HTTP_TIMEOUT_S))
    health_timeout_s = max(0.1, min(health_timeout_s, DEFAULT_HTTP_TIMEOUT_S))
    ok, reason, models = await probe_ollama_endpoint(pixel_base, timeout_s=health_timeout_s)
    if not ok:
        routing["execution_backend"] = "local_ollama"
        routing["fallback_active"] = True
        routing["fallback_reason"] = f"pixel_probe_failed:{reason}"
        return base_url, routing, []

    routing["pixel_ollama_url"] = pixel_base
    routing["pixel_probe"] = "ok"
    return pixel_base, routing, models


async def _relay_picobot_react(
    payload: dict[str, Any], prompt: str, orchestrator: Any, api_module: Any
) -> dict[str, Any] | None:
    _ = api_module
    if not _should_react_filter(payload, prompt, orchestrator):
        return None
    timeout_s = _http_timeout(float(payload.get("react_timeout_s", DEFAULT_HTTP_TIMEOUT_S)))
    react_payload: dict[str, Any] = {"prompt": prompt}
    for key in ("react_agent_id", "react_session_key", "react_wake_mode", "task_type"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            react_payload[key] = value
    picobot_result = await _picobot_http_call(
        orchestrator=orchestrator,
        method="POST",
        paths=("/agent/react", "/react", "/v1/agent/react"),
        payload=react_payload,
        timeout_s=timeout_s,
    )
    if picobot_result.get("ok", False):
        return picobot_result
    brain_result = await _relay_brain_react(prompt, timeout_s=timeout_s)
    if brain_result.get("ok", False):
        brain_result["degraded"] = True
        brain_result["picobot_error"] = picobot_result.get("error", "picobot unavailable")
        return brain_result
    return {
        "ok": False,
        "error": (
            f"picobot unavailable: {picobot_result.get('error', 'unknown')}; "
            f"brain fallback failed: {brain_result.get('error', 'unknown')}"
        ),
    }


def _is_local_didier_api_url(base_url: str) -> bool:
    parsed = urlparse(str(base_url or "").strip())
    if not (parsed.hostname or "").strip():
        return False
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return port in {5003, 5010}


def _candidate_picobot_bases(orchestrator: Any) -> list[str]:
    cfg = orchestrator.config.get("picobot", {}) if orchestrator else {}
    if not isinstance(cfg, dict):
        cfg = {}
    candidates: list[str] = []
    for key in (
        "base_url",
        "url",
        "agent_url",
        "service_url",
        "worker_url",
        "runtime_url",
        "api_url",
    ):
        value = str(cfg.get(key, "")).strip()
        if value:
            candidates.append(value.rstrip("/"))
    candidates.extend(_PICOBOT_DEFAULT_BASES)
    deduped: list[str] = []
    seen: set[str] = set()
    for base in candidates:
        clean = str(base or "").strip().rstrip("/")
        if not clean:
            continue
        if _is_local_didier_api_url(clean):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)
    return deduped


def _agent_shared_snapshot() -> dict[str, Any]:
    snapshot = read_shared_state()
    return {
        "ts": time.time(),
        "hardware_profile": snapshot.get("hardware_profile", {}),
        "workers": snapshot.get("workers", {}),
    }


async def _picobot_http_call(
    *,
    orchestrator: Any,
    method: str,
    paths: tuple[str, ...],
    payload: dict[str, Any] | None,
    timeout_s: float,
) -> dict[str, Any]:
    timeout = _http_timeout(timeout_s)
    method_up = str(method or "GET").upper()
    last_error = "picobot endpoint unavailable"
    bases = _candidate_picobot_bases(orchestrator)
    for base in bases:
        for path in paths:
            endpoint = f"{base}{path}"
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if method_up == "GET":
                        response = await client.get(endpoint, params=payload or {})
                    else:
                        response = await client.request(method_up, endpoint, json=payload or {})
                if not response.is_success:
                    last_error = f"http {response.status_code} on {endpoint}"
                    continue
                try:
                    body: Any = response.json()
                except Exception:
                    body = {"response": response.text.strip()}
                if isinstance(body, dict):
                    data = dict(body)
                else:
                    data = {"response": str(body)}
                data.setdefault("ok", True)
                data.setdefault("source", "picobot")
                data.setdefault("endpoint", endpoint)
                return data
            except Exception as exc:
                last_error = f"{type(exc).__name__} on {endpoint}: {exc}"
    return {"ok": False, "error": last_error}


async def _relay_brain_react(prompt: str, *, timeout_s: float) -> dict[str, Any]:
    timeout = _http_timeout(timeout_s)
    request_payload = {"prompt": prompt, "task_type": "react_task"}
    try:
        response = await ipc_request(
            "POST",
            "/generate",
            service="brain",
            payload=request_payload,
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"brain relay exception: {exc}"}
    if not response.is_success:
        return {"ok": False, "error": f"brain relay http {response.status_code}"}
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    text = str(payload.get("response", "")).strip()
    return {
        "ok": True,
        "source": "brain_worker",
        "endpoint": "unix://brain/generate",
        "response": text,
        "data": payload,
    }


async def _metrics_from_picobot(orchestrator: Any, timeout_s: float) -> dict[str, Any]:
    return await _picobot_http_call(
        orchestrator=orchestrator,
        method="GET",
        paths=("/agent/metrics", "/metrics", "/health"),
        payload={},
        timeout_s=timeout_s,
    )


async def _tasks_from_picobot(orchestrator: Any, timeout_s: float) -> dict[str, Any]:
    return await _picobot_http_call(
        orchestrator=orchestrator,
        method="GET",
        paths=("/agent/tasks", "/tasks"),
        payload={},
        timeout_s=timeout_s,
    )


async def _route_from_picobot(
    orchestrator: Any,
    *,
    prompt: str,
    task_type: str,
    payload: dict[str, Any] | None,
    timeout_s: float,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "prompt": str(prompt or ""),
        "task_type": str(task_type or "chat"),
    }
    if isinstance(payload, dict):
        request_payload["context"] = dict(payload)
    return await _picobot_http_call(
        orchestrator=orchestrator,
        method="POST",
        paths=("/agent/route", "/route", "/v1/agent/route"),
        payload=request_payload,
        timeout_s=timeout_s,
    )


async def _memory_from_picobot(
    orchestrator: Any,
    *,
    include_content: bool,
    timeout_s: float,
) -> dict[str, Any]:
    return await _picobot_http_call(
        orchestrator=orchestrator,
        method="GET",
        paths=("/agent/memory", "/memory"),
        payload={"include_content": bool(include_content)},
        timeout_s=timeout_s,
    )


async def _memory_write_picobot(
    orchestrator: Any,
    *,
    path: str,
    content: str,
    append: bool,
    timeout_s: float,
) -> dict[str, Any]:
    return await _picobot_http_call(
        orchestrator=orchestrator,
        method="POST",
        paths=("/agent/memory", "/memory"),
        payload={"path": path, "content": content, "append": bool(append)},
        timeout_s=timeout_s,
    )


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


_TASK_INTENT_KEYWORDS = {
    "allume",
    "allumer",
    "eteins",
    "eteindre",
    "active",
    "desactive",
    "lance",
    "arrete",
    "stop",
    "rappelle",
    "rappelle moi",
    "programme",
    "planifie",
    "cree",
    "ajoute",
    "ouvre",
    "ferme",
    "envoie",
    "mets",
    "regle",
}


def _looks_like_task_request(text: str, *, is_voice: bool = False) -> bool:
    norm = _normalize_text(text)
    if not norm:
        return False

    conversational_prefixes = (
        "salut",
        "bonjour",
        "comment",
        "pourquoi",
        "qui",
        "qu est ce",
        "explique",
    )
    if any(norm.startswith(prefix) for prefix in conversational_prefixes) and not any(
        kw in norm for kw in _TASK_INTENT_KEYWORDS
    ):
        return False

    if any(kw in norm for kw in _TASK_INTENT_KEYWORDS):
        return True

    first_word = norm.split(" ", 1)[0]
    imperative_verbs = {"allume", "eteins", "lance", "arrete", "ouvre", "ferme", "ajoute", "cree"}
    if first_word in imperative_verbs:
        return True

    if is_voice and any(token in norm for token in ("fais", "vas y", "ok didier")):
        return True
    return False


def _extract_agent_reply(result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return ""
    candidate_keys = ("response", "reply", "message", "output", "text", "result")
    for key in candidate_keys:
        value = result.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = result.get("data")
    if isinstance(nested, dict):
        for key in candidate_keys:
            value = nested.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


async def _vision_see_user(timeout_s: float = 0.8) -> dict[str, Any] | None:
    timeout_s = max(0.2, min(float(timeout_s), 2.0))
    try:
        response = await ipc_request(
            "GET",
            "/vision/see_user",
            service="vision",
            timeout=timeout_s,
        )
    except Exception:
        return None
    if not response.is_success:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _vision_glance_text(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    if str(payload.get("status", "")).lower() != "ok":
        return ""
    if not bool(payload.get("seen", False)):
        return ""
    summary = str(payload.get("summary", "")).strip()
    if summary:
        return summary
    location = str(payload.get("location", "")).strip()
    if location and location.lower() != "inconnue":
        return f"Je te vois dans {location}."
    return "Je te vois bien devant la camera."


def _prepend_glance(response: str, glance_text: str) -> str:
    base = str(response or "").strip()
    intro = str(glance_text or "").strip()
    if not intro:
        return base
    if not base:
        return intro
    if _normalize_text(intro) in _normalize_text(base):
        return base
    return f"{intro} {base}".strip()


async def _queue_audio_worker_speak(text: str, timeout_s: float = 1.0) -> tuple[bool, str]:
    message = str(text or "").strip()
    if not message:
        return False, "empty_text"
    timeout_s = _http_timeout(timeout_s)
    try:
        response = await ipc_request(
            "POST",
            "/speak",
            service="audio",
            payload={"text": message},
            timeout=timeout_s,
        )
    except Exception as exc:
        return False, f"audio_worker_unavailable: {exc}"
    if not response.is_success:
        try:
            payload = response.json()
        except Exception:
            payload = {}
        detail = str(payload.get("detail") or payload.get("error") or f"http {response.status_code}")
        return False, detail
    return True, "queued"


async def _soundboks_ready(orchestrator: Any, api_module: Any) -> tuple[bool, str]:
    sink = str(orchestrator.config.get("bluetooth.sink_name", "")).strip()
    if not sink:
        return False, "sink_missing"
    try:
        sound = await api_module.asyncio.wait_for(
            api_module.asyncio.to_thread(api_module._check_soundboks_sink, sink),
            timeout=0.8,
        )
    except Exception as exc:
        return False, f"sound_check_failed: {exc}"
    if not isinstance(sound, dict):
        return False, "sound_status_invalid"
    if bool(sound.get("available", False)):
        return True, str(sound.get("matched_sink") or sound.get("sink") or sink)
    return False, "soundboks_absente_ou_non_connectee"


async def _deliver_dual_response(
    response_text: str,
    *,
    orchestrator: Any,
    api_module: Any,
) -> dict[str, Any]:
    text = str(response_text or "").strip()
    delivery: dict[str, Any] = {
        "audio": False,
        "audio_status": "written_only",
        "audio_note": "Enceinte absente: reponse ecrite uniquement.",
    }
    if not text:
        return delivery
    speaker_ok, speaker_detail = await _soundboks_ready(orchestrator, api_module)
    if not speaker_ok:
        delivery["audio_status"] = "speaker_unavailable"
        delivery["audio_detail"] = speaker_detail
        return delivery
    queued, queue_detail = await _queue_audio_worker_speak(text)
    if queued:
        return {
            "audio": True,
            "audio_status": "queued",
            "audio_detail": speaker_detail,
            "audio_note": "",
        }
    return {
        "audio": False,
        "audio_status": "queue_failed",
        "audio_detail": queue_detail,
        "audio_note": "Enceinte detectee mais TTS indisponible: reponse ecrite uniquement.",
    }


async def _generate_conversation_response(
    *,
    clean_prompt: str,
    task_type: str,
    expert_model: str | None,
    expert_system: str | None,
    backend_choice: dict[str, Any],
    payload: dict[str, Any],
    orchestrator: Any,
    api_module: Any,
) -> dict[str, Any]:
    base_url, backend_choice, preloaded_models = await _resolve_ollama_base_for_backend(
        orchestrator=orchestrator,
        backend_choice=backend_choice,
        payload=payload,
    )
    ask_profile_model = orchestrator.config.get(
        "ollama.model_profiles.ask",
        orchestrator.config.get("ollama.ask_model", None),
    )
    default_model = orchestrator.config.get("ollama.model", None)
    available_models = preloaded_models or await _list_ollama_models(base_url)
    resolved_model = _pick_model(
        available_models,
        [
            expert_model,
            str(backend_choice.get("recommended_model", "")).strip(),
            ask_profile_model,
            default_model,
        ],
    )
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
        async with httpx.AsyncClient(timeout=_http_timeout(timeout_s)) as client:
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
        # Safety fallback: if Pixel Ollama is slow/unreachable, retry once on local Pi.
        local_base_url = str(orchestrator.config.get("ollama.base_url", "http://localhost:11434")).strip().rstrip("/")
        can_retry_local = (
            str(backend_choice.get("execution_backend", "")).strip() == "pixel_ollama"
            and base_url != local_base_url
        )
        if can_retry_local:
            fallback_url = f"{local_base_url}/api/generate"
            try:
                async with httpx.AsyncClient(timeout=_http_timeout(timeout_s)) as client:
                    fallback_response = await client.post(fallback_url, json=payload_data)
                    fallback_response.raise_for_status()
                    fallback_data = fallback_response.json()
                response = str(fallback_data.get("response", "")).strip() or "Je t'ecoute."
                if _is_listening_only_response(response):
                    response = "Salut. Dis-moi l'action precise que tu veux lancer."
                backend_choice["execution_backend"] = "local_ollama"
                backend_choice["fallback_active"] = True
                backend_choice["fallback_reason"] = f"pixel_generate_failed:{_http_error_brief(exc)}"
                api_module.update_status(
                    thinking=False,
                    state="IDLE",
                    last_response=response,
                    last_response_at=api_module.time.time(),
                )
                return {
                    "response": response,
                    "model": resolved_model,
                    "task": False,
                    "route": "ollama",
                    "task_type": task_type,
                    "routing": backend_choice,
                }
            except Exception:
                pass
        backend_choice["fallback_active"] = True
        backend_choice["fallback_reason"] = (
            backend_choice.get("fallback_reason")
            or f"ollama_generate_failed:{_http_error_brief(exc)}"
        )
        api_module.update_status(thinking=False, state="IDLE", error=f"{_http_error_brief(exc)}")
        return {
            "response": "Je suis encore en charge. Reessaie dans quelques secondes.",
            "model": resolved_model,
            "task": False,
            "route": "stub",
            "task_type": task_type,
            "routing": backend_choice,
        }
    return {
        "response": response,
        "model": resolved_model,
        "task": False,
        "route": "ollama",
        "task_type": task_type,
        "routing": backend_choice,
    }


async def process_input(
    text: str,
    is_voice: bool = False,
    image_bytes: bytes | None = None,
    *,
    payload: dict[str, Any] | None = None,
    orchestrator: Any | None = None,
    api_module: Any | None = None,
) -> dict[str, Any]:
    from core import runtime_bridge as runtime_api

    _ = image_bytes  # Reserved for the vision-aware path (step 2).
    payload = payload or {}
    api_module = api_module or runtime_api
    orchestrator = orchestrator or api_module._require_orchestrator()

    prompt = str(text or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")

    clean_prompt, expert_model, expert_system, _expert = api_module._resolve_expert_prompt(
        prompt, orchestrator.config
    )
    vision_glance_payload: dict[str, Any] | None = None
    if bool(payload.get("vision_glance", True)):
        vision_timeout_s = float(payload.get("vision_timeout_s", 0.8))
        vision_glance_payload = await _vision_see_user(vision_timeout_s)
    glance_text = _vision_glance_text(vision_glance_payload)

    force_task = bool(payload.get("force_task", False))
    is_task = force_task or _looks_like_task_request(clean_prompt, is_voice=is_voice)
    task_type = _infer_task_type(clean_prompt, payload, is_task=is_task)
    backend_choice = choose_backend(clean_prompt, task_type, payload)

    if is_task:
        react_payload = dict(payload)
        react_payload["react_filter"] = True
        react_payload["task_type"] = task_type
        react_result = await _relay_picobot_react(
            payload=react_payload,
            prompt=clean_prompt,
            orchestrator=orchestrator,
            api_module=api_module,
        )
        react_text = _extract_agent_reply(react_result)
        if not react_text and isinstance(react_result, dict) and react_result.get("ok", False):
            react_text = "Tache Picobot en cours."
        if not react_text:
            error_msg = (
                str((react_result or {}).get("error", "")).strip()
                if isinstance(react_result, dict)
                else ""
            )
            react_text = (
                f"Picobot indisponible: {error_msg}"
                if error_msg
                else "Picobot indisponible pour cette tache."
            )
        react_text = _prepend_glance(react_text, glance_text)
        return {
            "response": react_text,
            "task": True,
            "route": "picobot",
            "task_type": task_type,
            "routing": backend_choice,
            "react": react_result,
            "vision": vision_glance_payload,
            "source": "process_input",
        }

    result = await _generate_conversation_response(
        clean_prompt=clean_prompt,
        task_type=task_type,
        expert_model=expert_model,
        expert_system=expert_system,
        backend_choice=backend_choice,
        payload=payload,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    react_payload = dict(payload)
    react_payload["task_type"] = task_type
    react_result = await _relay_picobot_react(
        payload=react_payload,
        prompt=clean_prompt,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    if react_result is not None:
        result["react"] = react_result
    result["response"] = _prepend_glance(str(result.get("response", "")), glance_text)
    result["vision"] = vision_glance_payload
    result["source"] = "process_input"
    return result


@router.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("audio_playback"):
        raise HTTPException(status_code=503, detail="arbitration_denied:audio_playback")
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

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("audio_playback"):
        raise HTTPException(status_code=503, detail="arbitration_denied:audio_playback")
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
        await api_module.asyncio.to_thread(
            api_module.subprocess.run,
            cmd,
            check=True,
            timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
        )
    except Exception:
        raise HTTPException(status_code=500, detail="paplay failed")
    return {"status": "played", "sink": sink}


@router.post("/ask")
@circuit_breaker("ai.ask")
async def ask(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    force_task = bool(payload.get("force_task", False))
    is_task = force_task or _looks_like_task_request(
        prompt,
        is_voice=bool(payload.get("is_voice", False)),
    )
    if not is_task and not arbitrator.request_resource("llm_generation"):
        raise HTTPException(status_code=503, detail="arbitration_denied:llm_generation")
    return await process_input(
        prompt,
        is_voice=bool(payload.get("is_voice", False)),
        image_bytes=None,
        payload=payload,
        api_module=api_module,
    )


@router.post("/agent/react")
async def agent_react(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(
        payload.get("prompt")
        or payload.get("text")
        or payload.get("message")
        or ""
    ).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    backend_choice = choose_backend(prompt, "react_task", payload)
    orchestrator = api_module._require_orchestrator()
    react_payload = dict(payload)
    react_payload["react_filter"] = True
    react_payload["task_type"] = "react_task"
    result = await _relay_picobot_react(
        payload=react_payload,
        prompt=prompt,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    if result is None:
        result = {"ok": False, "error": "picobot react relay skipped"}
    result["routing"] = backend_choice
    return result


@router.post("/agent/route")
async def agent_route(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(
        payload.get("prompt")
        or payload.get("text")
        or payload.get("message")
        or ""
    ).strip()
    task_type = str(payload.get("task_type", "chat")).strip() or "chat"
    timeout_s = _http_timeout(float(payload.get("timeout_s", DEFAULT_HTTP_TIMEOUT_S)))
    orchestrator = api_module._require_orchestrator()
    result = await _route_from_picobot(
        orchestrator,
        prompt=prompt,
        task_type=task_type,
        payload=payload,
        timeout_s=timeout_s,
    )
    if result.get("ok", False):
        return result
    return {
        "ok": True,
        "degraded": True,
        "source": "api_route_fallback",
        "error": result.get("error", "picobot route unavailable"),
        "task_type": task_type,
        "routing": choose_backend(prompt, task_type, payload),
        "ts": time.time(),
    }


@router.get("/agent/metrics")
async def agent_metrics(timeout_s: float = DEFAULT_HTTP_TIMEOUT_S) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    timeout_s = _http_timeout(timeout_s)
    orchestrator = api_module._require_orchestrator()
    result = await _metrics_from_picobot(orchestrator, timeout_s)
    if result.get("ok", False):
        return result
    return {
        "ok": True,
        "degraded": True,
        "error": result.get("error", "picobot unavailable"),
        "shared_state": _agent_shared_snapshot(),
    }


@router.get("/agent/tasks")
async def agent_tasks(timeout_s: float = DEFAULT_HTTP_TIMEOUT_S) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    timeout_s = _http_timeout(timeout_s)
    orchestrator = api_module._require_orchestrator()
    result = await _tasks_from_picobot(orchestrator, timeout_s)
    if result.get("ok", False):
        return result
    return {
        "ok": True,
        "degraded": True,
        "error": result.get("error", "picobot tasks unavailable"),
        "tasks": [],
        "shared_state": _agent_shared_snapshot(),
    }


@router.get("/agent/memory")
async def agent_memory(include_content: bool = False) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    result = await _memory_from_picobot(
        orchestrator,
        include_content=bool(include_content),
        timeout_s=DEFAULT_HTTP_TIMEOUT_S,
    )
    if not result.get("ok", False):
        return {
            "ok": True,
            "degraded": True,
            "error": result.get("error", "picobot memory unavailable"),
            "memory": {},
            "shared_state": _agent_shared_snapshot(),
        }
    return result


@router.post("/agent/memory")
async def agent_memory_write(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    path = str(payload.get("path", "")).strip()
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    content = str(payload.get("content", ""))
    append = bool(payload.get("append", False))
    orchestrator = api_module._require_orchestrator()
    result = await _memory_write_picobot(
        orchestrator,
        path=path,
        content=content,
        append=append,
        timeout_s=DEFAULT_HTTP_TIMEOUT_S,
    )
    if not result.get("ok", False):
        raise HTTPException(status_code=503, detail=result.get("error", "picobot memory write unavailable"))
    return result


@router.post("/coding")
@circuit_breaker("ai.coding")
async def coding(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("llm_generation"):
        raise HTTPException(status_code=503, detail="arbitration_denied:llm_generation")
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
        async with httpx.AsyncClient(timeout=_http_timeout(120)) as client:
            response = await client.post(url, json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return {"response": str(data.get("response", "")).strip()}


@router.get("/ollama/models")
async def ollama_models() -> dict[str, Any]:
    global _OLLAMA_MODELS_CACHE, _OLLAMA_MODELS_CACHE_TS
    now = time.time()
    if (
        _OLLAMA_MODELS_CACHE is not None
        and (now - _OLLAMA_MODELS_CACHE_TS) <= _OLLAMA_MODELS_CACHE_TTL_S
    ):
        return dict(_OLLAMA_MODELS_CACHE)
    if _OLLAMA_MODELS_LOCK.locked() and _OLLAMA_MODELS_CACHE is not None:
        return dict(_OLLAMA_MODELS_CACHE)

    from core import runtime_bridge as api_module

    async with _OLLAMA_MODELS_LOCK:
        now = time.time()
        if (
            _OLLAMA_MODELS_CACHE is not None
            and (now - _OLLAMA_MODELS_CACHE_TS) <= _OLLAMA_MODELS_CACHE_TTL_S
        ):
            return dict(_OLLAMA_MODELS_CACHE)

        orchestrator = api_module._require_orchestrator()
        base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
        url = f"{base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=_http_timeout(10)) as client:
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")

        if isinstance(data, dict):
            _OLLAMA_MODELS_CACHE = dict(data)
            _OLLAMA_MODELS_CACHE_TS = time.time()
        return data


@router.get("/asr/status")
async def asr_status() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    return api_module._read_asr_status()


@router.post("/asr/wake-test")
async def asr_wake_test(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("asr_ingest"):
        raise HTTPException(status_code=503, detail="arbitration_denied:asr_ingest_paused")
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
                    subprocess.run,
                    whisper_cmd,
                    check=False,
                    capture_output=True,
                    timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
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
@circuit_breaker("ai.ask_and_speak")
async def ask_and_speak(payload: dict[str, Any]) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    arbitrator = get_resource_arbitrator()
    orchestrator = api_module._require_orchestrator()
    music = orchestrator.get_tentacle("music")
    is_task_request = bool(payload.get("force_task", False)) or _looks_like_task_request(
        prompt,
        is_voice=True,
    )

    # Voice task/action requests are delegated to Picobot first.
    if is_task_request:
        routed = await process_input(
            prompt,
            is_voice=True,
            payload=payload,
            orchestrator=orchestrator,
            api_module=api_module,
        )
        routed_response = str(routed.get("response", "")).strip()
        routed.update(
            await _deliver_dual_response(
                routed_response,
                orchestrator=orchestrator,
                api_module=api_module,
            )
        )
        return routed
    if not arbitrator.request_resource("llm_generation"):
        raise HTTPException(status_code=503, detail="arbitration_denied:llm_generation")

    ask_profile_model = orchestrator.config.get(
        "ollama.model_profiles.ask",
        orchestrator.config.get("ollama.ask_model", None),
    )
    default_model = orchestrator.config.get("ollama.model", None)
    clean_prompt, expert_model, expert_system, _expert = api_module._resolve_expert_prompt(
        prompt, orchestrator.config
    )
    task_type = _infer_task_type(clean_prompt, payload, is_task=False)
    backend_choice = choose_backend(clean_prompt, task_type, payload)
    base_url, backend_choice, preloaded_models = await _resolve_ollama_base_for_backend(
        orchestrator=orchestrator,
        backend_choice=backend_choice,
        payload=payload,
    )
    available_models = preloaded_models or await _list_ollama_models(base_url)
    react_payload = dict(payload)
    react_payload["task_type"] = task_type
    react_result = await _relay_picobot_react(
        payload=react_payload,
        prompt=clean_prompt,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    resolved_model = _pick_model(
        available_models,
        [
            expert_model,
            str(backend_choice.get("recommended_model", "")).strip(),
            ask_profile_model,
            default_model,
        ],
    )
    prompt_norm = _normalize_text(clean_prompt)
    if any(
        key in prompt_norm
        for key in ("parle moi en francais", "reponds en francais", "en francais")
    ):
        response = "D'accord, je te reponds en francais."
        result = {"response": response}
        result.update(
            await _deliver_dual_response(
                response,
                orchestrator=orchestrator,
                api_module=api_module,
            )
        )
        if react_result is not None:
            result["react"] = react_result
        result["task_type"] = task_type
        result["routing"] = backend_choice
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
            result = {
                "response": response,
                "actuator": {"id": actuator_id, "name": actuator_name, "action": action, "ok": ok},
            }
            result.update(
                await _deliver_dual_response(
                    response,
                    orchestrator=orchestrator,
                    api_module=api_module,
                )
            )
            if react_result is not None:
                result["react"] = react_result
            result["task_type"] = task_type
            result["routing"] = backend_choice
            return result

    if music and api_module._is_music_prompt(prompt):
        await music.play(prompt)
        response = "Musique lancée."
        result = {"response": response, "music": True}
        result.update(
            await _deliver_dual_response(
                response,
                orchestrator=orchestrator,
                api_module=api_module,
            )
        )
        if react_result is not None:
            result["react"] = react_result
        result["task_type"] = task_type
        result["routing"] = backend_choice
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
        async with httpx.AsyncClient(timeout=_http_timeout(timeout_s)) as client:
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
            async with httpx.AsyncClient(
                timeout=_http_timeout(min(timeout_s, 15.0))
            ) as client:
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
        local_base_url = str(orchestrator.config.get("ollama.base_url", "http://localhost:11434")).strip().rstrip("/")
        can_retry_local = (
            str(backend_choice.get("execution_backend", "")).strip() == "pixel_ollama"
            and base_url != local_base_url
        )
        if can_retry_local:
            fallback_url = f"{local_base_url}/api/generate"
            try:
                async with httpx.AsyncClient(timeout=_http_timeout(timeout_s)) as client:
                    fallback_response = await client.post(fallback_url, json=payload_data)
                    fallback_response.raise_for_status()
                    fallback_data = fallback_response.json()
                response = str(fallback_data.get("response", "")).strip() or "Je suis pret, donne-moi une action precise."
                backend_choice["execution_backend"] = "local_ollama"
                backend_choice["fallback_active"] = True
                backend_choice["fallback_reason"] = f"pixel_generate_failed:{_http_error_brief(exc)}"
                api_module.update_status(
                    thinking=False,
                    state="IDLE",
                    last_response=response,
                    last_response_at=api_module.time.time(),
                )
            except Exception:
                api_module.update_status(thinking=False, state="IDLE", error=f"{_http_error_brief(exc)}")
                response = "Je suis encore en charge. Reessaie dans quelques secondes."
        else:
            api_module.update_status(thinking=False, state="IDLE", error=f"{_http_error_brief(exc)}")
            response = "Je suis encore en charge. Reessaie dans quelques secondes."
    result = {"response": response}
    result.update(
        await _deliver_dual_response(
            response,
            orchestrator=orchestrator,
            api_module=api_module,
        )
    )
    if react_result is not None:
        result["react"] = react_result
    result["task_type"] = task_type
    result["routing"] = backend_choice
    return result
