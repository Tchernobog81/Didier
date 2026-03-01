"""Camera utility helpers for system routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable


@dataclass(frozen=True)
class CameraControlConfig:
    camera_device: Any = None
    width: Any = None
    height: Any = None
    fourcc: Any = None

    @classmethod
    def from_config(cls, config: Any) -> "CameraControlConfig":
        getter = getattr(config, "get", None)
        if not callable(getter):
            return cls()
        return cls(
            camera_device=getter("vision.camera_device", None),
            width=getter("vision.width", None),
            height=getter("vision.height", None),
            fourcc=getter("vision.fourcc", None),
        )


async def camera_holders_payload(
    config: CameraControlConfig,
    *,
    camera_holders_fn: Callable[[Any], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    return await camera_holders_fn(config.camera_device)


async def camera_reconnect_payload(
    config: CameraControlConfig,
    *,
    camera_reconnect_fn: Callable[[Any], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    return await camera_reconnect_fn(config.camera_device)


async def camera_force_format_payload(
    config: CameraControlConfig,
    *,
    camera_force_format_fn: Callable[[Any, Any, Any, Any], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    return await camera_force_format_fn(
        config.camera_device,
        config.width,
        config.height,
        config.fourcc,
    )
