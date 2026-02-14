"""Data models for future Edge AI backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class EdgeMode(str, Enum):
    """Runtime mode selection for vision execution."""

    CPU = "cpu_mode"
    HAILO = "hailo_mode"


@dataclass(frozen=True)
class EdgeModelConfig:
    """Model declaration only; no loading or inference in this layer."""

    name: str
    backend: str
    precision: str
    path: str | None = None
    enabled: bool = True


@dataclass
class EdgeModelRegistry:
    """Future model registry for Hailo and fallback multimodal paths."""

    yolo_int8: EdgeModelConfig = field(
        default_factory=lambda: EdgeModelConfig(
            name="yolov10n-int8",
            backend="hailo_tappas",
            precision="int8",
            path=None,
            enabled=True,
        )
    )
    moondream: EdgeModelConfig = field(
        default_factory=lambda: EdgeModelConfig(
            name="moondream",
            backend="ollama",
            precision="fp16_or_q4",
            path=None,
            enabled=True,
        )
    )
    qwen2_5_vl: EdgeModelConfig = field(
        default_factory=lambda: EdgeModelConfig(
            name="qwen2.5-vl",
            backend="ollama",
            precision="q4_or_q8",
            path=None,
            enabled=False,
        )
    )

    def as_dict(self) -> dict[str, dict[str, Any]]:
        return {
            "yolo_int8": self.yolo_int8.__dict__.copy(),
            "moondream": self.moondream.__dict__.copy(),
            "qwen2_5_vl": self.qwen2_5_vl.__dict__.copy(),
        }


def default_model_registry() -> EdgeModelRegistry:
    """Return default model declarations with no side effects."""

    return EdgeModelRegistry()

