"""Compatibility shim for legacy imports.

The active API lives in ``core.api``.
This module keeps minimal backward-compatibility for historical code paths.
"""

from __future__ import annotations

import asyncio
from typing import Any

from audio_service import AudioService
from core.api import app


class AsyncAudioService:
    """Async wrapper around the singleton audio service used by legacy Flask runtime."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._service = AudioService.get_instance(config or {})
        self.queue = self._service.queue

    async def speak(self, text: str) -> None:
        await asyncio.to_thread(self._service.speak, str(text))

    async def beep(self) -> None:
        await asyncio.to_thread(self._service.beep)

    async def clear(self) -> None:
        await asyncio.to_thread(self._service.clear)


__all__ = ["app", "AsyncAudioService"]
