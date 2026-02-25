"""LLM hardware-aware backend routing contracts for Didier."""

from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Mapping

from core.hardware_aware import get_best_model
from core.shared_state import read_state as read_shared_state

DEFAULT_CONFIG_PATH = Path(os.getenv("DIDIER_CONFIG_PATH", "config/config.json"))
_ROUTING_CACHE_TTL_S = 6.0

_DEFAULT_POLICY = {
    "task_aliases": {
        "ask": "chat",
        "conversation": "chat",
        "text": "chat",
        "voice": "chat",
        "stt": "asr",
        "speech_to_text": "asr",
        "text_to_speech": "tts",
        "npu_inference": "vision",
        "detection": "vision",
        "agent/react": "react_task",
        "react": "react_task",
    },
    "light_task_types": ["chat", "asr", "tts", "react_task"],
    "vision_task_types": ["vision"],
    "react_task_types": ["react_task"],
    "light_prompt": {
        "max_chars": 180,
        "max_words": 28,
    },
    "backends": {
        "local": "local_ollama",
        "react": "picobot_bridge",
        "vision": "pi_hailo_vision",
        "pixel_candidate": "pixel_tpu",
        "pixel_execution": "pixel_ollama",
    },
    "route_hints": {
        "local": "brain_local",
        "react": "picobot_bridge",
        "vision": "vision_worker",
        "pixel": "pixel_tpu_candidate",
    },
    "supported_devices": {
        "npu": ["hailo"],
        "tpu": ["pixel"],
    },
    "allow_unknown_devices": True,
}

_ROUTING_CACHE_LOCK = threading.Lock()
_ROUTING_CACHE_TS = 0.0
_ROUTING_CACHE: dict[str, Any] | None = None


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _normalize_token(value: Any) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _normalize_aliases(raw: Mapping[str, Any]) -> dict[str, str]:
    aliases = {
        str(k).strip().lower(): str(v).strip().lower()
        for k, v in raw.items()
        if str(k).strip() and str(v).strip()
    }
    return aliases


def _normalize_types(raw: list[Any], fallback: list[str]) -> set[str]:
    values = {str(item).strip().lower() for item in raw if str(item).strip()}
    if values:
        return values
    return {str(item).strip().lower() for item in fallback if str(item).strip()}


def _normalize_supported_devices(raw: Mapping[str, Any]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for key, value in raw.items():
        entries = []
        for item in _as_list(value):
            token = str(item).strip().lower()
            if token:
                entries.append(token)
        output[str(key).strip().lower()] = entries
    return output


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _extract_routing_section(config: Mapping[str, Any] | None) -> dict[str, Any]:
    root = _as_mapping(config)
    nested = _as_mapping(root.get("routing"))
    return nested if nested else root


def _build_routing_policy(routing_cfg: Mapping[str, Any] | None) -> dict[str, Any]:
    policy = json.loads(json.dumps(_DEFAULT_POLICY))
    cfg = _extract_routing_section(routing_cfg)

    aliases = _normalize_aliases(_as_mapping(cfg.get("task_aliases")))
    policy["task_aliases"].update(aliases)

    policy["light_task_types"] = sorted(
        _normalize_types(_as_list(cfg.get("light_task_types")), policy["light_task_types"])
    )
    policy["vision_task_types"] = sorted(
        _normalize_types(_as_list(cfg.get("vision_task_types")), policy["vision_task_types"])
    )
    policy["react_task_types"] = sorted(
        _normalize_types(_as_list(cfg.get("react_task_types")), policy["react_task_types"])
    )

    prompt_cfg = _as_mapping(cfg.get("light_prompt"))
    policy["light_prompt"]["max_chars"] = max(
        24,
        min(
            _as_int(
                prompt_cfg.get("max_chars", policy["light_prompt"]["max_chars"]),
                policy["light_prompt"]["max_chars"],
            ),
            4096,
        ),
    )
    policy["light_prompt"]["max_words"] = max(
        4,
        min(
            _as_int(
                prompt_cfg.get("max_words", policy["light_prompt"]["max_words"]),
                policy["light_prompt"]["max_words"],
            ),
            1024,
        ),
    )

    backend_cfg = _as_mapping(cfg.get("backends"))
    for key, value in backend_cfg.items():
        v = str(value).strip()
        if v:
            policy["backends"][str(key).strip()] = v

    route_hint_cfg = _as_mapping(cfg.get("route_hints"))
    for key, value in route_hint_cfg.items():
        v = str(value).strip()
        if v:
            policy["route_hints"][str(key).strip()] = v

    policy["supported_devices"] = _normalize_supported_devices(
        _as_mapping(cfg.get("supported_devices")) or _as_mapping(policy["supported_devices"])
    )
    policy["allow_unknown_devices"] = _as_bool(
        cfg.get("allow_unknown_devices", policy["allow_unknown_devices"]),
        default=True,
    )

    return policy


def _load_routing_policy(
    *,
    refresh: bool = False,
    routing_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if routing_config is not None:
        return _build_routing_policy(routing_config)

    global _ROUTING_CACHE_TS, _ROUTING_CACHE
    now = time.time()
    with _ROUTING_CACHE_LOCK:
        if not refresh and _ROUTING_CACHE is not None and (now - _ROUTING_CACHE_TS) < _ROUTING_CACHE_TTL_S:
            return json.loads(json.dumps(_ROUTING_CACHE))

        root = _read_json(DEFAULT_CONFIG_PATH)
        policy = _build_routing_policy(_as_mapping(root.get("routing")))
        _ROUTING_CACHE = policy
        _ROUTING_CACHE_TS = now
        return json.loads(json.dumps(policy))


def _normalize_task_type(task_type: str, aliases: Mapping[str, str]) -> str:
    raw = str(task_type or "").strip().lower()
    if not raw:
        return "chat"
    return str(aliases.get(raw, raw)).strip().lower() or "chat"


def _looks_light_prompt(prompt: str, *, max_chars: int, max_words: int) -> bool:
    text = str(prompt or "").strip()
    if not text:
        return True
    if len(text) > max_chars:
        return False
    return len(text.split()) <= max_words


def _extract_hardware_profile(shared_state: Mapping[str, Any] | None) -> dict[str, Any]:
    state = _as_mapping(shared_state) or _as_mapping(read_shared_state())
    profile = _as_mapping(state.get("hardware_profile"))
    npu = _as_mapping(profile.get("npu"))
    tpu = _as_mapping(profile.get("tpu"))
    return {
        "npu_available": bool(npu.get("available", False)),
        "npu_device_count": int(npu.get("device_count", 0) or 0),
        "pixel_detected": bool(tpu.get("pixel_detected", False)),
        "pixel_count": int(tpu.get("pixel_count", 0) or 0),
        "profile": profile,
    }


def _collect_device_tokens(profile: Mapping[str, Any], device_type: str) -> set[str]:
    tokens: set[str] = set()
    node = _as_mapping(profile.get(device_type))
    for key in ("type", "model", "name"):
        value = str(node.get(key, "")).strip()
        if value:
            tokens.add(value)
    for item in _as_list(node.get("devices")):
        value = str(item).strip()
        if value:
            tokens.add(value)

    if device_type == "tpu":
        for item in _as_list(node.get("pixel_devices")):
            entry = _as_mapping(item)
            for key in ("hostname", "ip"):
                value = str(entry.get(key, "")).strip()
                if value:
                    tokens.add(value)
            for service in _as_list(entry.get("services")):
                value = str(service).strip()
                if value:
                    tokens.add(value)
        if bool(node.get("pixel_detected", False)):
            tokens.add("pixel")

    return tokens


def _is_device_supported(
    profile: Mapping[str, Any],
    *,
    device_type: str,
    supported_devices: Mapping[str, list[str]],
    allow_unknown_devices: bool,
) -> bool:
    expected = [str(item).strip().lower() for item in supported_devices.get(device_type, []) if str(item).strip()]
    if not expected:
        return True

    observed = {_normalize_token(item) for item in _collect_device_tokens(profile, device_type) if _normalize_token(item)}
    if not observed:
        return bool(allow_unknown_devices)

    for wanted in expected:
        wanted_token = _normalize_token(wanted)
        if not wanted_token:
            continue
        for token in observed:
            if wanted_token in token or token in wanted_token:
                return True
    return False


def choose_backend(
    prompt: str,
    task_type: str,
    *,
    context: Mapping[str, Any] | None = None,
    shared_state: Mapping[str, Any] | None = None,
    routing_config: Mapping[str, Any] | None = None,
    refresh_config: bool = False,
) -> dict[str, Any]:
    policy = _load_routing_policy(refresh=refresh_config, routing_config=routing_config)
    aliases = _normalize_aliases(_as_mapping(policy.get("task_aliases")))
    normalized = _normalize_task_type(task_type, aliases)

    light_task_types = {str(item).strip().lower() for item in _as_list(policy.get("light_task_types")) if str(item).strip()}
    vision_task_types = {str(item).strip().lower() for item in _as_list(policy.get("vision_task_types")) if str(item).strip()}
    react_task_types = {str(item).strip().lower() for item in _as_list(policy.get("react_task_types")) if str(item).strip()}

    prompt_cfg = _as_mapping(policy.get("light_prompt"))
    max_chars = max(24, _as_int(prompt_cfg.get("max_chars", 180), 180))
    max_words = max(4, _as_int(prompt_cfg.get("max_words", 28), 28))

    hw = _extract_hardware_profile(shared_state)
    supported_devices = {
        str(key).strip().lower(): [str(item).strip().lower() for item in _as_list(value)]
        for key, value in _as_mapping(policy.get("supported_devices")).items()
    }
    allow_unknown_devices = _as_bool(policy.get("allow_unknown_devices", True), default=True)

    npu_supported = _is_device_supported(
        hw["profile"],
        device_type="npu",
        supported_devices=supported_devices,
        allow_unknown_devices=allow_unknown_devices,
    )
    tpu_supported = _is_device_supported(
        hw["profile"],
        device_type="tpu",
        supported_devices=supported_devices,
        allow_unknown_devices=allow_unknown_devices,
    )

    context_payload = dict(context or {})
    context_payload.setdefault("prompt_chars", len(str(prompt or "")))
    context_payload.setdefault("prompt_words", len(str(prompt or "").split()))
    context_payload.setdefault("npu_available", hw["npu_available"])
    context_payload.setdefault("pixel_detected", hw["pixel_detected"])
    context_payload.setdefault("task_type", normalized)

    recommendation = get_best_model(
        normalized,
        context_payload,
    )
    recommended_model = str(recommendation.get("model", "")).strip()
    recommendation_reason = str(recommendation.get("reason", "")).strip()
    source = str(recommendation.get("source", "fallback")).strip() or "fallback"

    backends = _as_mapping(policy.get("backends"))
    route_hints = _as_mapping(policy.get("route_hints"))

    local_backend = str(backends.get("local", "local_ollama")).strip() or "local_ollama"
    react_backend = str(backends.get("react", "picobot_bridge")).strip() or "picobot_bridge"
    vision_backend = str(backends.get("vision", "pi_hailo_vision")).strip() or "pi_hailo_vision"
    pixel_candidate_backend = str(backends.get("pixel_candidate", "pixel_tpu")).strip() or "pixel_tpu"
    pixel_execution_backend = str(backends.get("pixel_execution", local_backend)).strip() or local_backend

    preferred_backend = local_backend
    execution_backend = local_backend
    route_hint = str(route_hints.get("local", "brain_local")).strip() or "brain_local"
    priority_reason = "fallback_local"
    fallback_active = False

    if normalized in react_task_types:
        preferred_backend = react_backend
        execution_backend = react_backend
        route_hint = str(route_hints.get("react", "picobot_bridge")).strip() or "picobot_bridge"
        priority_reason = "task_orchestration_picobot"
    elif normalized in vision_task_types and bool(hw["npu_available"]) and bool(npu_supported):
        preferred_backend = vision_backend
        execution_backend = vision_backend
        route_hint = str(route_hints.get("vision", "vision_worker")).strip() or "vision_worker"
        priority_reason = "vision_on_hailo"
    elif (
        normalized in light_task_types
        and bool(hw["pixel_detected"])
        and bool(tpu_supported)
        and _looks_light_prompt(prompt, max_chars=max_chars, max_words=max_words)
    ):
        preferred_backend = pixel_candidate_backend
        execution_backend = pixel_execution_backend
        route_hint = str(route_hints.get("pixel", "pixel_tpu_candidate")).strip() or "pixel_tpu_candidate"
        priority_reason = "light_task_pixel_preferred"
        fallback_active = execution_backend != preferred_backend

    return {
        "task_type": normalized,
        "preferred_backend": preferred_backend,
        "execution_backend": execution_backend,
        "route_hint": route_hint,
        "priority_reason": priority_reason,
        "recommended_model": recommended_model,
        "recommendation_source": source,
        "recommendation_reason": recommendation_reason,
        "provider": str(recommendation.get("provider", "llmfit")),
        "score": str(recommendation.get("score", "good")),
        "fallback_active": fallback_active,
        "pixel_detected": bool(hw["pixel_detected"]),
        "pixel_count": int(hw["pixel_count"]),
        "npu_available": bool(hw["npu_available"]),
        "npu_device_count": int(hw["npu_device_count"]),
        "npu_supported": bool(npu_supported),
        "tpu_supported": bool(tpu_supported),
    }
