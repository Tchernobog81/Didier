"""Safe, non-blocking Hailo detection helpers."""

from __future__ import annotations

import glob
import importlib.util
import os
from ctypes.util import find_library
from functools import lru_cache
from typing import Any

_DEVICE_GLOBS = (
    "/dev/hailo*",
    "/sys/class/hailo*",
    "/sys/bus/pci/devices/*/hailo*",
)
_LIBRARIES = ("hailort", "hailo_rt", "libhailort")
_PY_MODULES = ("hailo_platform", "pyhailort", "hailo")
_FORCE_ENV = "DIDIER_FORCE_HAILO"


def _is_truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _is_falsy(value: str) -> bool:
    return value.strip().lower() in {"0", "false", "no", "off"}


def _probe_devices() -> bool:
    for pattern in _DEVICE_GLOBS:
        if glob.glob(pattern):
            return True
    return False


def _probe_libraries() -> bool:
    for lib_name in _LIBRARIES:
        if find_library(lib_name):
            return True
    return False


def _probe_python_modules() -> bool:
    for module_name in _PY_MODULES:
        try:
            if importlib.util.find_spec(module_name) is not None:
                return True
        except Exception:
            continue
    return False


@lru_cache(maxsize=1)
def detect_hailo() -> bool:
    """Return True when Hailo presence is likely detected.

    Detection is intentionally conservative and safe:
    - environment override (for testing)
    - device path presence
    - shared library presence
    - python module presence
    """

    forced = os.getenv(_FORCE_ENV, "")
    if forced:
        if _is_truthy(forced):
            return True
        if _is_falsy(forced):
            return False

    return _probe_devices() or _probe_libraries() or _probe_python_modules()


def reset_hailo_detection_cache() -> None:
    detect_hailo.cache_clear()


def hailo_probe_report() -> dict[str, Any]:
    """Optional diagnostics for logs or troubleshooting."""

    forced = os.getenv(_FORCE_ENV, "")
    return {
        "forced_env": forced or None,
        "devices_detected": _probe_devices(),
        "libraries_detected": _probe_libraries(),
        "python_modules_detected": _probe_python_modules(),
        "hailo_present": detect_hailo(),
    }

