"""Shared guard helpers for vision routes."""

from __future__ import annotations

from typing import Any

from core.config_access import npu_settings
from core.vision_npu_policy import npu_requirement_error


class VisionRouteGuardError(RuntimeError):
    """Raised when a vision route precondition is not satisfied."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(str(detail))
        self.status_code = int(status_code)
        self.detail = str(detail)


def _config_subject(orchestrator: Any) -> Any:
    if orchestrator is None:
        return {}
    loaded = getattr(orchestrator, "loaded_config", None)
    if loaded is not None:
        return loaded
    runtime = getattr(orchestrator, "runtime_config", None)
    if runtime is not None:
        return runtime
    return getattr(orchestrator, "config", {})


def get_vision_tentacle(orchestrator: Any) -> Any | None:
    if orchestrator is None or not hasattr(orchestrator, "get_tentacle"):
        return None
    try:
        return orchestrator.get_tentacle("vision")
    except Exception:
        return None


def require_vision_tentacle(
    orchestrator: Any,
    *,
    missing_detail: str = "vision tentacle not loaded",
    missing_status_code: int = 503,
) -> Any:
    vision = get_vision_tentacle(orchestrator)
    if not vision:
        raise VisionRouteGuardError(missing_status_code, missing_detail)
    return vision


def require_vision_capability(
    orchestrator: Any,
    capability: str,
    *,
    missing_detail: str = "vision tentacle not loaded",
    missing_status_code: int = 503,
    unsupported_detail: str,
    unsupported_status_code: int = 501,
) -> Any:
    vision = require_vision_tentacle(
        orchestrator,
        missing_detail=missing_detail,
        missing_status_code=missing_status_code,
    )
    if not hasattr(vision, str(capability)):
        raise VisionRouteGuardError(unsupported_status_code, unsupported_detail)
    return vision


def enforce_npu_requirement(orchestrator: Any, vision: Any) -> None:
    required_for_vision = bool(npu_settings(_config_subject(orchestrator)).required_for_vision)
    if not required_for_vision or not hasattr(vision, "get_status"):
        return
    try:
        status = vision.get_status()
    except Exception:
        status = {}
    reason = npu_requirement_error(
        status,
        required_for_vision=required_for_vision,
    )
    if reason:
        raise VisionRouteGuardError(503, reason)
