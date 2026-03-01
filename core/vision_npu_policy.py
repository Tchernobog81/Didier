"""Pure policy helpers for enforcing real NPU-backed vision."""

from __future__ import annotations

from typing import Any
from typing import Mapping


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def is_hailo_vision_active(status: Mapping[str, Any] | None) -> bool:
    data = _as_mapping(status)
    detector = str(data.get("detector", "")).strip().lower()
    if detector != "hailo":
        return False
    return bool(data.get("ready", False))


def npu_requirement_error(
    status: Mapping[str, Any] | None,
    *,
    required_for_vision: bool,
) -> str | None:
    if not bool(required_for_vision):
        return None
    if is_hailo_vision_active(status):
        return None
    data = _as_mapping(status)
    detector = str(data.get("detector", "unknown")).strip() or "unknown"
    ready = bool(data.get("ready", False))
    return f"npu_required_for_vision:{detector}:{'ready' if ready else 'not_ready'}"


def vision_npu_status(
    *,
    detector_name: str,
    detector_ready: bool,
    required_for_vision: bool,
) -> dict[str, Any]:
    detector = str(detector_name or "unknown").strip().lower()
    active = detector == "hailo" and bool(detector_ready)
    if active:
        target = "npu"
        reason = "hailo_active"
    elif bool(required_for_vision):
        target = "blocked"
        reason = "npu_required_but_inactive"
    else:
        target = "cpu"
        reason = "fallback_or_cpu_mode"
    return {
        "required": bool(required_for_vision),
        "active": active,
        "execution_target": target,
        "reason": reason,
    }
