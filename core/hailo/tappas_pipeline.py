"""Future TAPPAS pipeline skeleton.

No runtime dependency is required in CPU-only mode.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .monitor import detect_hailo


@dataclass
class TappasPipeline:
    """Placeholder object for the future Hailo TAPPAS runtime."""

    enabled: bool = field(default_factory=detect_hailo)
    started: bool = False
    frames_seen: int = 0

    @property
    def is_available(self) -> bool:
        return self.enabled

    def start(self) -> bool:
        """Future setup hook. Returns False when Hailo is not available."""

        if not self.enabled:
            self.started = False
            return False
        self.started = True
        return True

    def stop(self) -> None:
        self.started = False

    def process_frame(self, frame: Any) -> list[dict[str, Any]]:
        """Future inference hook.

        Current behavior is safe no-op to preserve CPU-only compatibility.
        """

        if not self.enabled:
            return []
        self.frames_seen += 1
        # Real TAPPAS YOLO INT8 inference will be added in a later tranche.
        return []

    def status(self) -> dict[str, Any]:
        return {
            "backend": "tappas_stub",
            "enabled": self.enabled,
            "started": self.started,
            "frames_seen": self.frames_seen,
        }

