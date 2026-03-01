"""Pure helpers to plan camera capture without touching hardware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Iterator


@dataclass(frozen=True)
class CaptureSourceConfig:
    camera_index: int = 0
    camera_device: Any = None
    camera_source: Any = None
    capture_backend: str = "auto"
    width: Any = None
    height: Any = None
    fps: Any = None
    fourcc: Any = None


@dataclass(frozen=True)
class CaptureAttempt:
    backend_name: str
    source: Any
    api_preference: int | None = None


def _clean_source(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return value


def resolve_capture_source(config: CaptureSourceConfig) -> Any:
    source = _clean_source(config.camera_source)
    if source is not None:
        return source
    device = _clean_source(config.camera_device)
    if device is not None:
        return device
    return int(config.camera_index)


def source_uses_network_transport(source: Any) -> bool:
    if not isinstance(source, str):
        return False
    lowered = source.strip().lower()
    return "://" in lowered or lowered.startswith(("rtsp:", "udp:", "tcp:", "http:"))


def can_use_v4l2_fallback(config: CaptureSourceConfig) -> bool:
    source = resolve_capture_source(config)
    return not source_uses_network_transport(source)


def build_gstreamer_pipeline(config: CaptureSourceConfig) -> str | None:
    source = resolve_capture_source(config)
    if source is None or source_uses_network_transport(source):
        return None
    device = str(source)
    width = int(config.width or 640)
    height = int(config.height or 480)
    fps = int(config.fps or 30)
    fourcc = str(config.fourcc or "YUYV").upper()
    if fourcc == "YUYV":
        fourcc = "YUY2"
    return (
        f"v4l2src device={device} "
        f"! video/x-raw,format={fourcc},width={width},height={height},framerate={fps}/1 "
        "! videoconvert ! appsink"
    )


def iter_capture_attempts(
    config: CaptureSourceConfig,
    *,
    gstreamer_pipeline: str | None,
    cap_gstreamer: int,
    cap_v4l2: int,
) -> Iterator[CaptureAttempt]:
    source = resolve_capture_source(config)
    backend = str(config.capture_backend or "auto").strip().lower()
    if source_uses_network_transport(source):
        yield CaptureAttempt("opencv", source, None)
        return

    if backend == "gstreamer" and gstreamer_pipeline:
        yield CaptureAttempt("gstreamer", gstreamer_pipeline, cap_gstreamer)
    yield CaptureAttempt("v4l2", source, cap_v4l2)
    yield CaptureAttempt("opencv", source, None)

    has_device = _clean_source(config.camera_device) is not None
    has_source = _clean_source(config.camera_source) is not None
    if has_device and not has_source:
        camera_index = int(config.camera_index)
        yield CaptureAttempt("index-v4l2", camera_index, cap_v4l2)
        yield CaptureAttempt("index-opencv", camera_index, None)

    if backend != "gstreamer" and gstreamer_pipeline:
        yield CaptureAttempt("gstreamer", gstreamer_pipeline, cap_gstreamer)
