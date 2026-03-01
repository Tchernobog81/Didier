"""Pure policy helpers for primary and secondary vision streams."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Mapping


def _as_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): raw for key, raw in value.items()}


def _coerce_bool(value: Any, default: bool) -> bool:
    if value is None:
        return bool(default)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _coerce_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def stream_emit_interval(
    *,
    configured_fps: int,
    target_fps: int | None = None,
    follow_target: bool = True,
) -> float:
    fps = max(1, min(int(configured_fps or 20), 60))
    if follow_target and target_fps is not None:
        try:
            fps = int(target_fps)
        except Exception:
            pass
    fps = max(1, min(int(fps), 60))
    return max(1.0 / float(fps), 0.03)


@dataclass(frozen=True)
class PrimaryStreamConfig:
    enable_live: bool = False
    primary_fallback_secondary: bool = False
    api_local_capture_enabled: bool = True
    primary_stale_fallback_seconds: float = 2.5
    camera_index: int = 0
    camera_device: Any = None
    width: Any = None
    height: Any = None
    fps: int = 20
    fourcc: Any = None
    kill_on_open: bool = False

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "PrimaryStreamConfig":
        data = _as_mapping(mapping)
        return cls(
            enable_live=_coerce_bool(data.get("enable_live"), False),
            primary_fallback_secondary=_coerce_bool(
                data.get("primary_fallback_secondary"),
                False,
            ),
            api_local_capture_enabled=_coerce_bool(
                data.get("api_local_capture_enabled"),
                True,
            ),
            primary_stale_fallback_seconds=max(
                1.0,
                _coerce_float(data.get("primary_stale_fallback_seconds"), 2.5),
            ),
            camera_index=_coerce_int(data.get("camera_index"), 0),
            camera_device=data.get("camera_device"),
            width=data.get("width"),
            height=data.get("height"),
            fps=max(1, _coerce_int(data.get("fps"), 20)),
            fourcc=data.get("fourcc"),
            kill_on_open=_coerce_bool(data.get("kill_on_open"), False),
        )


@dataclass(frozen=True)
class SecondaryStreamConfig:
    enabled: bool = True
    input_url: str = "udp://0.0.0.0:1234"
    fps: int = 15

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "SecondaryStreamConfig":
        data = _as_mapping(mapping)
        return cls(
            enabled=_coerce_bool(data.get("enabled"), True),
            input_url=str(data.get("input_url", "udp://0.0.0.0:1234") or "").strip(),
            fps=max(1, _coerce_int(data.get("fps"), 15)),
        )


@dataclass(frozen=True)
class PrimaryStreamDecision:
    use_live_stream: bool
    should_try_secondary_fallback: bool
    primary_stream_stale: bool


@dataclass(frozen=True)
class SecondaryStreamPlan:
    input_url: str
    fps: int


@dataclass(frozen=True)
class PrimaryCameraPlan:
    api_local_capture_enabled: bool
    camera_index: int
    camera_device: Any
    width: Any
    height: Any
    fps: int
    fourcc: Any
    kill_on_open: bool


def evaluate_primary_stream(
    *,
    config: PrimaryStreamConfig,
    has_vision: bool,
    has_live_jpeg: bool,
    cached_jpeg: bytes | None,
    last_frame_ts: float,
    now: float,
) -> PrimaryStreamDecision:
    if not has_vision or not config.enable_live or not has_live_jpeg:
        return PrimaryStreamDecision(
            use_live_stream=False,
            should_try_secondary_fallback=False,
            primary_stream_stale=False,
        )

    cached_jpeg_present = bool(cached_jpeg)
    primary_stream_stale = not cached_jpeg_present
    if last_frame_ts > 0.0:
        age_s = max(0.0, float(now) - float(last_frame_ts))
        primary_stream_stale = (age_s > config.primary_stale_fallback_seconds) or (
            not cached_jpeg_present
        )
    elif cached_jpeg_present:
        primary_stream_stale = False

    return PrimaryStreamDecision(
        use_live_stream=not primary_stream_stale,
        should_try_secondary_fallback=(
            bool(primary_stream_stale) and bool(config.primary_fallback_secondary)
        ),
        primary_stream_stale=bool(primary_stream_stale),
    )


def build_secondary_stream_plan(
    *,
    config: SecondaryStreamConfig,
    target_fps: int,
    ffmpeg_available: bool,
) -> tuple[SecondaryStreamPlan | None, str | None]:
    if not config.enabled:
        return None, "secondary stream disabled"
    if not config.input_url:
        return None, "input_url required"
    if not ffmpeg_available:
        return None, "ffmpeg not installed"
    _ = target_fps
    return SecondaryStreamPlan(
        input_url=config.input_url,
        fps=max(1, int(config.fps)),
    ), None


def build_primary_camera_plan(
    *,
    config: PrimaryStreamConfig,
    target_fps: int,
) -> PrimaryCameraPlan:
    return PrimaryCameraPlan(
        api_local_capture_enabled=bool(config.api_local_capture_enabled),
        camera_index=int(config.camera_index),
        camera_device=config.camera_device,
        width=config.width,
        height=config.height,
        fps=max(1, int(target_fps or config.fps)),
        fourcc=config.fourcc,
        kill_on_open=bool(config.kill_on_open),
    )
