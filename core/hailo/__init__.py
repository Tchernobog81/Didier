"""Optional Hailo / Edge AI scaffolding for Didier.

This package is intentionally passive:
- no mandatory runtime dependency
- no endpoint wiring
- no startup side effects
"""

from .detector import (
    CpuVisionBackend,
    HailoVisionBackend,
    VisionBackend,
    build_backend,
    select_mode,
)
from .models import EdgeMode, EdgeModelConfig, EdgeModelRegistry, default_model_registry
from .monitor import detect_hailo, hailo_probe_report, reset_hailo_detection_cache

__all__ = [
    "CpuVisionBackend",
    "HailoVisionBackend",
    "VisionBackend",
    "build_backend",
    "select_mode",
    "EdgeMode",
    "EdgeModelConfig",
    "EdgeModelRegistry",
    "default_model_registry",
    "detect_hailo",
    "hailo_probe_report",
    "reset_hailo_detection_cache",
]

