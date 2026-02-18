"""Runtime bridge for routers.

Routers must not import ``core.api`` directly to avoid tight coupling and
circular-import side effects. This bridge lazily proxies attributes to
``core.api`` at access time.
"""

from __future__ import annotations

from typing import Any


def _api_module() -> Any:
    from core import api as api_module

    return api_module


def __getattr__(name: str) -> Any:
    return getattr(_api_module(), name)
