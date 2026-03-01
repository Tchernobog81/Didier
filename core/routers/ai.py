import asyncio
import json
import re
import os
import subprocess
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from core.ai_ask_and_speak_service import AskAndSpeakDeps
from core.ai_ask_and_speak_service import handle_ask_and_speak
from core.ai_backend_policy import resolve_gemini_boost_config
from core.ai_coding_service import CodingGenerationDeps
from core.ai_coding_service import CodingServiceError
from core.ai_coding_service import generate_coding_response
from core.ai_conversation_service import ConversationGenerationDeps
from core.ai_conversation_service import ConversationServiceError
from core.ai_conversation_service import generate_conversation_response as generate_conversation_response_service
from core.ai_process_service import ProcessInputDeps
from core.ai_process_service import process_input as process_input_service
from core.ai_config import ollama_cfg as _ollama_cfg
from core.ai_config import picobot_cfg as _picobot_cfg
from core.ai_config import coding_cfg as _coding_cfg
from core.ai_config import prepare_chat_text as _prepare_chat_text
from core.ai_config import prepare_tts_text as _prepare_tts_text
from core.ai_config import routing_cfg as _routing_cfg
from core.backend_routing import choose_backend as choose_backend_contract
from core.brain_client import generate_from_brain
from core.ollama_targeting import probe_ollama_endpoint
from core.ollama_targeting import resolve_pixel_ollama_base_url
from core.picobot_client import memory_from_picobot
from core.picobot_client import memory_write_picobot
from core.picobot_client import metrics_from_picobot
from core.picobot_client import react_from_picobot
from core.picobot_client import route_from_picobot
from core.picobot_client import tasks_from_picobot
from core.text_compaction import text_stats
from core.routers.guards import circuit_breaker
from core.resource_arbitrator import get_resource_arbitrator
from core.shared_state import read_state as read_shared_state
from shared.ipc import request as ipc_request

router = APIRouter()
DEFAULT_HTTP_TIMEOUT_S = 2.0
DEFAULT_LLM_HTTP_TIMEOUT_S = 12.0
DEFAULT_SUBPROCESS_TIMEOUT_S = 2.0
_OLLAMA_MODELS_CACHE_TTL_S = 5.0
_OLLAMA_MODELS_CACHE: dict[str, Any] | None = None
_OLLAMA_MODELS_CACHE_TS = 0.0
_OLLAMA_MODELS_LOCK = asyncio.Lock()
_OLLAMA_TAGS_CACHE: dict[str, dict[str, Any]] = {}
_OLLAMA_TAGS_CACHE_LOCK = asyncio.Lock()
_GEMINI_BOOST_MEMORY_LOCK = asyncio.Lock()
_GEMINI_BOOST_MEMORY_PATH_DEFAULT = "data/gemini_boost_memory.jsonl"


def _runtime_qos_snapshot() -> dict[str, Any]:
    mode = "NOMINAL"
    llm_profile = "full"
    audio_queue_size = 0
    audio_speaking = False
    try:
        arbitration = get_resource_arbitrator().snapshot()
    except Exception:
        arbitration = {}
    if isinstance(arbitration, dict):
        mode = str(arbitration.get("mode", mode)).upper() or "NOMINAL"
        limits = arbitration.get("limits", {})
        if isinstance(limits, dict):
            llm_profile = str(limits.get("llm_profile", llm_profile)).strip().lower() or "full"
    try:
        workers = read_shared_state().get("workers", {})
    except Exception:
        workers = {}
    if isinstance(workers, dict):
        audio = workers.get("audio", {})
        if isinstance(audio, dict):
            try:
                audio_queue_size = int(audio.get("queue_size", 0) or 0)
            except Exception:
                audio_queue_size = 0
            audio_speaking = bool(audio.get("speaking", False))
    return {
        "mode": mode,
        "llm_profile": llm_profile,
        "audio_queue_size": max(0, audio_queue_size),
        "audio_speaking": audio_speaking,
    }


def _http_timeout(seconds: float | int, *, upper: float = DEFAULT_HTTP_TIMEOUT_S) -> float:
    return max(0.1, min(float(seconds), max(0.1, float(upper))))


def _llm_http_timeout(seconds: float | int) -> float:
    return _http_timeout(seconds, upper=DEFAULT_LLM_HTTP_TIMEOUT_S)


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
    async with httpx.AsyncClient(timeout=_http_timeout(timeout_s, upper=40.0)) as client:
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
    cache_key = str(base_url or "").strip().rstrip("/")
    now = time.time()
    async with _OLLAMA_TAGS_CACHE_LOCK:
        cached = dict(_OLLAMA_TAGS_CACHE.get(cache_key, {}) or {})
    cached_models = cached.get("models", []) if isinstance(cached.get("models"), list) else []
    cached_ts = float(cached.get("ts", 0.0) or 0.0)
    if cached_models and (now - cached_ts) <= _OLLAMA_MODELS_CACHE_TTL_S:
        return [str(item) for item in cached_models if str(item).strip()]

    url = f"{cache_key}/api/tags"
    try:
        async with httpx.AsyncClient(timeout=_http_timeout(2.0, upper=2.0)) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except asyncio.CancelledError:
        raise
    except Exception:
        return [str(item) for item in cached_models if str(item).strip()]
    models: list[str] = []
    for item in payload.get("models", []):
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("model")
        if name:
            models.append(str(name))
    async with _OLLAMA_TAGS_CACHE_LOCK:
        _OLLAMA_TAGS_CACHE[cache_key] = {"ts": time.time(), "models": list(models)}
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


_TRUNCATED_TAIL_TOKENS = {
    "a",
    "au",
    "aux",
    "avec",
    "car",
    "ce",
    "ces",
    "d",
    "dans",
    "de",
    "des",
    "du",
    "en",
    "et",
    "la",
    "le",
    "les",
    "mon",
    "ma",
    "mes",
    "notre",
    "ou",
    "pour",
    "qu",
    "que",
    "sans",
    "sur",
    "ton",
    "ta",
    "tes",
    "un",
    "une",
    "vers",
    "votre",
}


def _finalize_model_response(text: str) -> str:
    response = str(text or "").strip()
    if not response:
        return ""
    if response.endswith("..."):
        return "Je n'ai pas pu finir la reponse. Reformule en une phrase plus courte."
    normalized = _normalize_text(response)
    tokens = [tok for tok in normalized.split() if tok]
    if len(tokens) >= 5:
        tail = tokens[-1]
        if tail in _TRUNCATED_TAIL_TOKENS or len(tail) <= 1:
            return "Je n'ai pas pu finir la reponse. Reformule en une phrase plus courte."
    if response[-1] not in ".!?":
        response = f"{response}."
    return response


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
    cfg = _picobot_cfg(orchestrator)
    if "react_filter" in payload:
        return bool(payload.get("react_filter"))
    if _looks_like_vision_anomaly(prompt):
        return bool(cfg.anomaly_react_enabled)
    return bool(cfg.react_filter_default)


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


def _extract_openai_chat_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message", {}) if isinstance(first, dict) else {}
    if isinstance(message, dict):
        content = str(message.get("content", "")).strip()
        if content:
            return content
    text = str(first.get("text", "")).strip() if isinstance(first, dict) else ""
    if text:
        return text
    return ""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]

def _resolve_repo_path(path_str: str) -> Path:
    raw = Path(str(path_str or "").strip()).expanduser()
    if raw.is_absolute():
        return raw
    return (_repo_root() / raw).resolve()


def _read_recent_boost_memory(path: Path, limit: int) -> list[dict[str, str]]:
    if limit <= 0 or not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    items: list[dict[str, str]] = []
    for line in reversed(lines):
        line = str(line or "").strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        prompt = str(payload.get("prompt", "")).strip()
        response = str(payload.get("response", "")).strip()
        if not prompt or not response:
            continue
        items.append({"prompt": prompt, "response": response})
        if len(items) >= limit:
            break
    items.reverse()
    return items


def _trim_text(value: str, max_len: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_len:
        return text
    return text[: max(0, max_len - 1)].rstrip() + "..."


def _build_gemini_prompt(
    prompt: str,
    *,
    system_prompt: str | None,
    memory: list[dict[str, str]],
) -> str:
    lines: list[str] = [
        "Tu es Didier. Reponds en francais, de maniere concise et utile.",
        "Si l'information est indisponible, explique clairement la limite puis propose l'action suivante.",
    ]
    system = str(system_prompt or "").strip()
    if system:
        lines.append(f"Consigne systeme: {system}")
    if memory:
        lines.append("Memoire recente utilisateur:")
        for index, item in enumerate(memory, start=1):
            mem_prompt = _trim_text(item.get("prompt", ""), 220)
            mem_response = _trim_text(item.get("response", ""), 260)
            lines.append(f"{index}. U: {mem_prompt}")
            lines.append(f"   D: {mem_response}")
    lines.append(f"Question actuelle: {prompt}")
    lines.append("Reponse:")
    return "\n".join(lines)


def _extract_gemini_text(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidates", []) if isinstance(payload, dict) else []
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content", {})
        if not isinstance(content, dict):
            continue
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        text_parts: list[str] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            text = str(part.get("text", "")).strip()
            if text:
                text_parts.append(text)
        if text_parts:
            return "\n".join(text_parts).strip()
    return ""


def _append_boost_memory_sync(path: Path, *, prompt: str, response: str, max_bytes: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": time.time(),
        "prompt": _trim_text(prompt, 500),
        "response": _trim_text(response, 800),
    }
    line = json.dumps(entry, ensure_ascii=False)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
    try:
        current_size = path.stat().st_size
    except Exception:
        return
    if current_size <= max_bytes:
        return
    try:
        all_lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return
    kept: list[str] = []
    kept_bytes = 0
    for raw_line in reversed(all_lines):
        clean = str(raw_line or "").strip()
        if not clean:
            continue
        line_size = len(clean.encode("utf-8")) + 1
        if kept and (kept_bytes + line_size) > max_bytes:
            break
        kept.append(clean)
        kept_bytes += line_size
        if len(kept) >= 400:
            break
    kept.reverse()
    output = ("\n".join(kept) + "\n") if kept else ""
    path.write_text(output, encoding="utf-8")


async def _append_boost_memory(
    *,
    config: dict[str, Any],
    prompt: str,
    response: str,
) -> None:
    if not config.get("memory_enabled", False):
        return
    path = _resolve_repo_path(str(config.get("memory_path", _GEMINI_BOOST_MEMORY_PATH_DEFAULT)))
    max_bytes = int(config.get("memory_max_bytes", 262144) or 262144)
    async with _GEMINI_BOOST_MEMORY_LOCK:
        await asyncio.to_thread(
            _append_boost_memory_sync,
            path,
            prompt=prompt,
            response=response,
            max_bytes=max_bytes,
        )


async def _try_gemini_boost_chat(
    *,
    orchestrator: Any,
    prompt: str,
    system_prompt: str | None,
    max_tokens: int,
    timeout_s: float,
) -> tuple[str | None, str | None]:
    ollama_cfg = _ollama_cfg(orchestrator)
    config = resolve_gemini_boost_config(_picobot_cfg(orchestrator))
    if not config.get("enabled", False):
        return None, "gemini_boost_disabled"
    api_key = str(config.get("api_key", "")).strip()
    base_url = str(config.get("base_url", "")).strip().rstrip("/")
    model = str(config.get("model", "")).strip()
    if not api_key:
        return None, "gemini_api_key_missing"
    if not base_url or not model:
        return None, "gemini_config_missing"
    memory_items = int(config.get("memory_items", 0) or 0)
    memory: list[dict[str, str]] = []
    if config.get("memory_enabled", False) and memory_items > 0:
        memory_path = _resolve_repo_path(
            str(config.get("memory_path", _GEMINI_BOOST_MEMORY_PATH_DEFAULT))
        )
        memory = await asyncio.to_thread(
            _read_recent_boost_memory,
            memory_path,
            memory_items,
        )
    prompt_text = _build_gemini_prompt(
        prompt,
        system_prompt=system_prompt,
        memory=memory,
    )
    endpoint = f"{base_url}/models/{model}:generateContent"
    body = {
        "contents": [{"parts": [{"text": prompt_text}]}],
        "generationConfig": {
            "temperature": float(ollama_cfg.temperature),
            "maxOutputTokens": max(64, min(int(max_tokens or 128), 384)),
        },
    }
    capped_timeout_s = min(
        float(config.get("timeout_s", timeout_s) or timeout_s),
        float(timeout_s),
    )
    capped_timeout_s = max(0.4, min(capped_timeout_s, DEFAULT_LLM_HTTP_TIMEOUT_S))
    try:
        async with httpx.AsyncClient(timeout=_llm_http_timeout(capped_timeout_s)) as client:
            response = await client.post(
                endpoint,
                params={"key": api_key},
                json=body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            response.raise_for_status()
            payload = response.json()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, _http_error_brief(exc)
    text = _extract_gemini_text(payload if isinstance(payload, dict) else {})
    if not text:
        return None, "gemini_empty_response"
    final_text = _finalize_model_response(str(text).strip())
    if final_text:
        await _append_boost_memory(config=config, prompt=prompt, response=final_text)
    return final_text, None


async def _try_pixel_openai_chat(
    *,
    orchestrator: Any,
    prompt: str,
    system_prompt: str | None,
    max_tokens: int,
    timeout_s: float,
) -> tuple[str | None, str | None]:
    ollama_cfg = _ollama_cfg(orchestrator)
    picobot_cfg = _picobot_cfg(orchestrator)
    base_url = str(picobot_cfg.llm_endpoint).strip().rstrip("/")
    model = str(picobot_cfg.llm_model).strip()
    if not base_url or not model:
        return None, "pixel_openai_config_missing"

    api_key = str(picobot_cfg.llm_api_key).strip() or "sk-dummy"
    endpoint = f"{base_url}/chat/completions"
    messages: list[dict[str, str]] = []
    if system_prompt:
        messages.append({"role": "system", "content": str(system_prompt).strip()})
    messages.append({"role": "user", "content": f"Reponds en francais, brievement.\n{prompt}"})
    body = {
        "model": model,
        "messages": messages,
        "temperature": float(ollama_cfg.temperature),
        "max_tokens": max(48, min(int(max_tokens or 96), 220)),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    try:
        async with httpx.AsyncClient(timeout=_llm_http_timeout(timeout_s)) as client:
            response = await client.post(endpoint, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return None, _http_error_brief(exc)
    text = _extract_openai_chat_text(payload if isinstance(payload, dict) else {})
    if not text:
        return None, "pixel_openai_empty_response"
    return text, None


async def _resolve_ollama_base_for_backend(
    *,
    orchestrator: Any,
    backend_choice: dict[str, Any],
    payload: dict[str, Any] | None = None,
) -> tuple[str, dict[str, Any], list[str]]:
    base_url = str(_ollama_cfg(orchestrator).base_url).strip().rstrip("/")
    routing_cfg = _routing_cfg(orchestrator)
    config_view = getattr(orchestrator, "loaded_config", None) or getattr(orchestrator, "config", None)
    routing = dict(backend_choice or {})
    execution_backend = str(routing.get("execution_backend", "local_ollama")).strip() or "local_ollama"
    if execution_backend != "pixel_ollama":
        return base_url, routing, []

    root_cfg = {
        "routing": config_view.get("routing", {}) if config_view is not None else {},
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

    health_timeout_s = float(routing_cfg.pixel_ollama_health_timeout_s)
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
    default_react_timeout_s = float(_picobot_cfg(orchestrator).react_timeout_s)
    timeout_s = _http_timeout(
        float(payload.get("react_timeout_s", default_react_timeout_s)),
        upper=7.0,
    )
    react_payload: dict[str, Any] = {
        "prompt": prompt,
        "timeout_s": timeout_s,
        "react_timeout_s": timeout_s,
    }
    for key in ("react_agent_id", "react_session_key", "react_wake_mode", "task_type", "boost"):
        value = payload.get(key)
        if value is not None and str(value).strip():
            react_payload[key] = value
    picobot_result = await react_from_picobot(
        picobot_config=_picobot_cfg(orchestrator),
        payload=react_payload,
        timeout_s=timeout_s,
    )
    if picobot_result.get("ok", False):
        return picobot_result
    brain_fallback_enabled = bool(_picobot_cfg(orchestrator).brain_fallback_enabled)
    if not brain_fallback_enabled:
        return {
            "ok": False,
            "error": f"picobot unavailable: {picobot_result.get('error', 'unknown')}",
        }
    brain_result = await generate_from_brain(
        prompt=prompt,
        task_type="react_task",
        timeout_s=timeout_s,
    )
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

def _agent_shared_snapshot() -> dict[str, Any]:
    snapshot = read_shared_state()
    return {
        "ts": time.time(),
        "hardware_profile": snapshot.get("hardware_profile", {}),
        "workers": snapshot.get("workers", {}),
    }
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
    "donne",
    "donne moi",
    "dis",
    "verifie",
    "verifier",
    "check",
    "statut",
    "status",
    "etat",
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

_TASK_GENERIC_QUERY_KEYWORDS = {
    "donne",
    "donne moi",
    "dis",
    "verifie",
    "verifier",
    "check",
    "statut",
    "status",
    "etat",
}

_TASK_TARGET_HINTS = {
    "actionneur",
    "allume",
    "arrete",
    "asr",
    "audio",
    "camera",
    "capteur",
    "device",
    "didier",
    "eteins",
    "flux",
    "lampe",
    "lumiere",
    "micro",
    "npu",
    "pixel",
    "prise",
    "service",
    "ssh",
    "systeme",
    "vision",
    "worker",
}

_WEB_QUERY_FORCE_HINTS = {
    "internet",
    "web",
    "en ligne",
    "online",
    "actualite",
    "actualites",
    "news",
    "meteo",
    "weather",
    "temperature",
    "forecast",
    "bourse",
    "crypto",
    "bitcoin",
    "ethereum",
    "prix",
    "cours",
    "taux",
    "taux de change",
    "trafic",
    "horaires",
    "horaire",
    "vol",
    "train",
    "bus",
    "resultat",
    "resultats",
    "score",
    "match",
    "aujourd hui",
    "demain",
    "ce soir",
    "ce weekend",
    "ce week end",
    "maintenant",
    "en ce moment",
}

_WEB_QUERY_LOCAL_HINTS = set(_TASK_TARGET_HINTS) | {
    "raspberry",
    "pi",
    "didier",
    "orchestrateur",
    "service",
    "processus",
}

_WEB_QUERY_SMALLTALK_PREFIXES = (
    "salut",
    "bonjour",
    "bonsoir",
    "merci",
    "ca va",
    "comment vas tu",
    "qui es tu",
    "tu es qui",
)

_WEB_QUERY_QUESTION_PREFIXES = {
    "qui",
    "quoi",
    "quand",
    "ou",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "combien",
    "who",
    "what",
    "when",
    "where",
    "how",
}


def _contains_keyword_phrase(norm_text: str, keyword: str) -> bool:
    text_tokens = [tok for tok in str(norm_text or "").split() if tok]
    keyword_tokens = [tok for tok in _normalize_text(keyword).split() if tok]
    if not text_tokens or not keyword_tokens:
        return False
    size = len(keyword_tokens)
    if size == 1:
        return keyword_tokens[0] in text_tokens
    for index in range(0, len(text_tokens) - size + 1):
        if text_tokens[index : index + size] == keyword_tokens:
            return True
    return False


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
        "quel",
        "quelle",
        "quels",
        "quelles",
        "peux tu",
        "peut tu",
        "peux-tu",
        "peut-tu",
        "qu est ce",
        "explique",
    )
    if any(norm.startswith(prefix) for prefix in conversational_prefixes) and not any(
        _contains_keyword_phrase(norm, kw) for kw in _TASK_INTENT_KEYWORDS
    ):
        return False

    if any(_contains_keyword_phrase(norm, kw) for kw in _TASK_INTENT_KEYWORDS):
        generic_query = any(
            _contains_keyword_phrase(norm, kw) for kw in _TASK_GENERIC_QUERY_KEYWORDS
        )
        if generic_query and not any(
            _contains_keyword_phrase(norm, hint) for hint in _TASK_TARGET_HINTS
        ):
            return False
        return True

    first_word = norm.split(" ", 1)[0]
    imperative_verbs = {
        "donne",
        "dis",
        "verifie",
        "check",
        "allume",
        "eteins",
        "lance",
        "arrete",
        "ouvre",
        "ferme",
        "ajoute",
        "cree",
    }
    if first_word in imperative_verbs:
        return True

    if is_voice and any(token in norm for token in ("fais", "vas y", "ok didier")):
        return True
    return False


def _looks_like_web_query(text: str) -> bool:
    norm = _normalize_text(text)
    if not norm:
        return False
    if any(norm.startswith(prefix) for prefix in _WEB_QUERY_SMALLTALK_PREFIXES):
        return False

    if any(_contains_keyword_phrase(norm, hint) for hint in _WEB_QUERY_FORCE_HINTS):
        return True

    first_word = norm.split(" ", 1)[0]
    if first_word not in _WEB_QUERY_QUESTION_PREFIXES:
        return False

    if any(_contains_keyword_phrase(norm, hint) for hint in _WEB_QUERY_LOCAL_HINTS):
        return False
    return True


def _looks_like_identity_query(text: str) -> bool:
    norm = _normalize_text(text)
    if not norm:
        return False
    hints = (
        "tu es quel modele",
        "quel modele",
        "quel modèle",
        "modele utilises",
        "modèle utilises",
        "quel backend",
        "quelle route",
        "qui es tu",
        "tu es qui",
    )
    return any(hint in norm for hint in hints)


def _looks_like_local_status_query(text: str) -> bool:
    norm = _normalize_text(text)
    if not norm:
        return False
    status_hints = ("statut", "status", "etat", "etat rapide")
    scope_hints = ("didier", "systeme", "système", "runtime", "backend")
    if not any(hint in norm for hint in status_hints):
        return False
    return any(hint in norm for hint in scope_hints)


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


def _humanize_task_failure_reason(error_msg: str) -> str:
    text = str(error_msg or "").strip()
    if not text:
        return "raison inconnue"
    norm = _normalize_text(text)
    if "timeout" in norm or "timed out" in norm:
        return "delai depasse vers le service distant"
    if "connection refused" in norm or "no route to host" in norm:
        return "connexion au service distant indisponible"
    if "container unavailable" in norm:
        return "service Picobot indisponible"
    if "model missing" in norm or "base url missing" in norm:
        return "configuration du modele incomplete"
    if "http 401" in norm or "http 403" in norm:
        return "acces refuse par le modele"
    if "http 404" in norm:
        return "endpoint du modele introuvable"
    if "empty response" in norm:
        return "le modele ne renvoie aucune reponse"
    return text[:120]


def _build_task_apology(error_msg: str) -> str:
    reason = _humanize_task_failure_reason(error_msg)
    return f"Desole, je ne peux pas traiter cette demande pour le moment: {reason}."


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

async def _queue_audio_worker_speak(
    text: str,
    timeout_s: float = 1.0,
    *,
    drop_pending: bool = False,
    interrupt_current: bool = False,
) -> tuple[bool, str]:
    message = str(text or "").strip()
    if not message:
        return False, "empty_text"
    timeout_s = _http_timeout(timeout_s)
    payload: dict[str, Any] = {"text": message, "interrupt_current": bool(interrupt_current)}
    if drop_pending:
        payload["drop_pending"] = True
    try:
        response = await ipc_request(
            "POST",
            "/speak",
            service="audio",
            payload=payload,
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


async def _deliver_dual_response(
    response_text: str,
    *,
    orchestrator: Any,
    api_module: Any,
    is_voice_request: bool = False,
) -> dict[str, Any]:
    text = str(response_text or "").strip()
    response_metrics = text_stats(text)
    delivery: dict[str, Any] = {
        "audio": False,
        "audio_status": "written_only",
        "audio_note": "Audio indisponible: reponse ecrite uniquement.",
        "diagnostics": {
            "response": response_metrics,
            "tts": {"chars": 0, "words": 0, "sentences": 0},
            "audio_queue_ms": 0,
        },
    }
    if not text:
        return delivery
    qos = _runtime_qos_snapshot()
    tts_text = _prepare_tts_text(text, orchestrator, qos=qos)
    tts_metrics = text_stats(tts_text)
    diagnostics = delivery.get("diagnostics", {})
    if isinstance(diagnostics, dict):
        diagnostics["tts"] = tts_metrics
    if not tts_text:
        return delivery
    mode = str(qos.get("mode", "NOMINAL")).upper()
    queue_size = int(qos.get("audio_queue_size", 0) or 0)
    speaking = bool(qos.get("audio_speaking", False))
    audio_busy = speaking or queue_size > 0
    if not bool(is_voice_request) and audio_busy:
        return {
            "audio": False,
            "audio_status": "skipped_busy",
            "audio_detail": "audio_busy_non_voice",
            "audio_note": "Audio saute: sortie texte priorisee pendant la lecture.",
            "diagnostics": delivery.get("diagnostics"),
        }
    interrupt_current = bool(audio_busy and mode in {"TENDU", "SURVIE"})
    queue_timeout_s = 1.2
    if mode == "SURVIE":
        queue_timeout_s = 0.9
    elif mode == "TENDU":
        queue_timeout_s = 1.0
    queue_started = time.perf_counter()
    queued, queue_detail = await _queue_audio_worker_speak(
        tts_text,
        timeout_s=queue_timeout_s,
        drop_pending=True,
        interrupt_current=interrupt_current,
    )
    queue_elapsed_ms = int(max(0.0, (time.perf_counter() - queue_started) * 1000))
    diagnostics = delivery.get("diagnostics", {})
    if isinstance(diagnostics, dict):
        diagnostics["audio_queue_ms"] = queue_elapsed_ms
    if queued:
        return {
            "audio": True,
            "audio_status": "queued",
            "audio_detail": "audio_worker",
            "audio_interrupt": bool(interrupt_current),
            "audio_note": "",
            "diagnostics": delivery.get("diagnostics"),
        }
    return {
        "audio": False,
        "audio_status": "queue_failed",
        "audio_detail": queue_detail,
        "audio_note": "Audio non disponible pour cette reponse.",
        "diagnostics": delivery.get("diagnostics"),
    }


def _stamp_server_elapsed(result: dict[str, Any], started_at: float) -> dict[str, Any]:
    payload = dict(result or {})
    payload["server_elapsed_ms"] = int(max(0.0, (time.perf_counter() - started_at) * 1000))
    return payload


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
    deps = ConversationGenerationDeps(
        runtime_qos_snapshot=_runtime_qos_snapshot,
        flag_enabled=_flag_enabled,
        try_gemini_boost_chat=_try_gemini_boost_chat,
        try_pixel_openai_chat=_try_pixel_openai_chat,
        resolve_ollama_base_for_backend=_resolve_ollama_base_for_backend,
        list_ollama_models=_list_ollama_models,
        pick_model=_pick_model,
        finalize_model_response=_finalize_model_response,
        is_listening_only_response=_is_listening_only_response,
        llm_http_timeout=_llm_http_timeout,
        http_error_brief=_http_error_brief,
        resolve_gemini_boost_config=resolve_gemini_boost_config,
    )
    try:
        return await generate_conversation_response_service(
            clean_prompt=clean_prompt,
            task_type=task_type,
            expert_model=expert_model,
            expert_system=expert_system,
            backend_choice=backend_choice,
            payload=payload,
            orchestrator=orchestrator,
            api_module=api_module,
            ollama_config=_ollama_cfg(orchestrator),
            picobot_config=_picobot_cfg(orchestrator),
            routing_config=_routing_cfg(orchestrator),
            deps=deps,
        )
    except ConversationServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


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

    api_module = api_module or runtime_api
    orchestrator = orchestrator or api_module._require_orchestrator()

    prompt = str(text or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")

    deps = ProcessInputDeps(
        resolve_expert_prompt=api_module._resolve_expert_prompt,
        vision_see_user=_vision_see_user,
        vision_glance_text=_vision_glance_text,
        looks_like_web_query=_looks_like_web_query,
        looks_like_task_request=_looks_like_task_request,
        infer_task_type=_infer_task_type,
        choose_backend=choose_backend,
        relay_picobot_react=_relay_picobot_react,
        extract_agent_reply=_extract_agent_reply,
        build_task_apology=_build_task_apology,
        prepend_glance=_prepend_glance,
        generate_conversation_response=_generate_conversation_response,
    )
    return await process_input_service(
        prompt=prompt,
        is_voice=is_voice,
        image_bytes=image_bytes,
        payload=payload,
        orchestrator=orchestrator,
        api_module=api_module,
        deps=deps,
    )


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
    result = await route_from_picobot(
        picobot_config=_picobot_cfg(orchestrator),
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
    result = await metrics_from_picobot(
        picobot_config=_picobot_cfg(orchestrator),
        timeout_s=timeout_s,
    )
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
    result = await tasks_from_picobot(
        picobot_config=_picobot_cfg(orchestrator),
        timeout_s=timeout_s,
    )
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
    result = await memory_from_picobot(
        picobot_config=_picobot_cfg(orchestrator),
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
    result = await memory_write_picobot(
        picobot_config=_picobot_cfg(orchestrator),
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
    arbitrator = get_resource_arbitrator()
    if not arbitrator.request_resource("llm_generation"):
        raise HTTPException(status_code=503, detail="arbitration_denied:llm_generation")
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    deps = CodingGenerationDeps(
        list_ollama_models=_list_ollama_models,
        pick_model=_pick_model,
        request_timeout=lambda: _http_timeout(120, upper=15.0),
    )
    try:
        return await generate_coding_response(
            prompt=prompt,
            ollama_config=_ollama_cfg(orchestrator),
            coding_config=_coding_cfg(orchestrator),
            deps=deps,
        )
    except CodingServiceError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


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
        base_url = str(_ollama_cfg(orchestrator).base_url).strip().rstrip("/")
        url = f"{base_url}/api/tags"
        try:
            async with httpx.AsyncClient(timeout=_http_timeout(10, upper=10.0)) as client:
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

    request_started_at = time.perf_counter()
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    arbitrator = get_resource_arbitrator()
    orchestrator = api_module._require_orchestrator()
    deps = AskAndSpeakDeps(
        looks_like_web_query=_looks_like_web_query,
        looks_like_task_request=_looks_like_task_request,
        process_input=process_input,
        prepare_chat_text=_prepare_chat_text,
        runtime_qos_snapshot=_runtime_qos_snapshot,
        resolve_expert_prompt=api_module._resolve_expert_prompt,
        infer_task_type=_infer_task_type,
        choose_backend=choose_backend,
        normalize_text=_normalize_text,
        looks_like_identity_query=_looks_like_identity_query,
        looks_like_local_status_query=_looks_like_local_status_query,
        deliver_dual_response=_deliver_dual_response,
        parse_switch_action=_parse_switch_action,
        resolve_actuator_target=_resolve_actuator_target,
        is_music_prompt=api_module._is_music_prompt,
        generate_conversation_response=_generate_conversation_response,
    )
    result = await handle_ask_and_speak(
        prompt=prompt,
        payload=payload,
        orchestrator=orchestrator,
        api_module=api_module,
        arbitrator=arbitrator,
        ollama_config=_ollama_cfg(orchestrator),
        deps=deps,
    )
    return _stamp_server_elapsed(result, request_started_at)
