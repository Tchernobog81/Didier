"""Dual-mode vision backend skeleton (CPU / Hailo)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .models import EdgeMode
from .monitor import detect_hailo
from .tappas_pipeline import TappasPipeline

Detection = dict[str, Any]
CpuDetectFn = Callable[[Any], list[Detection]]


class VisionBackend(Protocol):
    """Common backend interface for current and future vision engines."""

    mode: str

    def detect(self, frame: Any) -> list[Detection]:
        ...

    def status(self) -> dict[str, Any]:
        ...


@dataclass
class CpuVisionBackend:
    """Adapter for the current CPU pipeline behavior."""

    detect_fn: CpuDetectFn | None = None
    mode: str = EdgeMode.CPU.value

    def detect(self, frame: Any) -> list[Detection]:
        if self.detect_fn is None:
            return []
        try:
            result = self.detect_fn(frame)
            return result if isinstance(result, list) else []
        except Exception:
            return []

    def status(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "backend": "cpu",
            "hailo_available": detect_hailo(),
        }


@dataclass
class HailoVisionBackend:
    """Future backend using TAPPAS + Hailo runtime."""

    pipeline: TappasPipeline = field(default_factory=TappasPipeline)
    mode: str = EdgeMode.HAILO.value

    def detect(self, frame: Any) -> list[Detection]:
        return self.pipeline.process_frame(frame)

    def status(self) -> dict[str, Any]:
        info = self.pipeline.status()
        info.update(
            {
                "mode": self.mode,
                "backend": "hailo",
                "hailo_available": self.pipeline.is_available,
            }
        )
        return info


def select_mode() -> str:
    """Select mode without changing the current vision API behavior."""

    return EdgeMode.HAILO.value if detect_hailo() else EdgeMode.CPU.value


def build_backend(cpu_detect_fn: CpuDetectFn | None = None) -> VisionBackend:
    """Create backend instance with transparent cpu/hailo fallback."""

    if select_mode() == EdgeMode.HAILO.value:
        return HailoVisionBackend()
    return CpuVisionBackend(detect_fn=cpu_detect_fn)

