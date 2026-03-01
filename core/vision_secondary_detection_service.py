"""Runtime orchestration helpers for secondary vision detections."""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable

from core.vision_secondary_service import SecondaryDetectionsState
from core.vision_secondary_service import secondary_empty_payload
from core.vision_secondary_service import secondary_min_interval_s
from core.vision_stream_service import SecondaryStreamConfig


def _cached_or_empty(
    state: SecondaryDetectionsState,
    *,
    now: float,
    source: str,
    reason: str,
    stream_ts: float = 0.0,
) -> dict[str, Any]:
    cached = state.response_from_cached(
        now,
        source=source,
        stream_ts=stream_ts,
    )
    if cached is not None:
        return cached
    return secondary_empty_payload(reason, stream_ts=stream_ts)


async def _await_maybe(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


@dataclass(frozen=True)
class VisionSecondaryDetectionDeps:
    now: Callable[[], float]
    request_secondary_stream: Callable[[], bool]
    get_stream: Callable[[str, int], Any]
    decode_frame: Callable[[bytes], Awaitable[Any] | Any]
    detect_secondary_frame: Callable[[Any, Any], Awaitable[Any] | Any]


async def collect_secondary_detections(
    *,
    arbitrator: Any,
    state: SecondaryDetectionsState,
    refresh_lock: Any,
    stream_config: SecondaryStreamConfig,
    vision: Any,
    deps: VisionSecondaryDetectionDeps,
) -> dict[str, Any]:
    min_interval_s = secondary_min_interval_s(arbitrator)
    now = float(deps.now())
    if state.last_payload is not None and (now - state.last_refresh_ts) < min_interval_s:
        cached = state.response_from_cached(
            now,
            source="secondary_cache",
        )
        if cached is not None:
            return cached

    if not deps.request_secondary_stream():
        held = state.hold_last_non_empty_payload(
            now,
            state_reason="hold_last_non_empty:arbitration_denied:secondary_stream",
        )
        if held is not None:
            return held
        return secondary_empty_payload("arbitration_denied:secondary_stream")

    if not vision:
        return secondary_empty_payload("vision tentacle not loaded")
    if not callable(getattr(vision, "detect_secondary_frame", None)):
        return secondary_empty_payload("secondary detections not supported")
    if not stream_config.enabled:
        return secondary_empty_payload("secondary stream disabled")
    if not stream_config.input_url:
        return secondary_empty_payload("input_url required")

    stream = deps.get_stream(stream_config.input_url, stream_config.fps)
    if refresh_lock.locked():
        cached = state.response_from_cached(
            now,
            source="secondary_cache_locked",
        )
        if cached is not None:
            return cached
        return secondary_empty_payload("secondary detection busy")

    async with refresh_lock:
        now = float(deps.now())
        min_interval_s = secondary_min_interval_s(arbitrator)
        if state.last_payload is not None and (now - state.last_refresh_ts) < min_interval_s:
            cached = state.response_from_cached(
                now,
                source="secondary_cache",
            )
            if cached is not None:
                return cached

        frame_bytes, stream_ts = stream.get_last()
        if not frame_bytes:
            return _cached_or_empty(
                state,
                now=now,
                source="secondary_stale_cache",
                reason="secondary stream not ready",
                stream_ts=stream_ts,
            )
        frame = await _await_maybe(deps.decode_frame(frame_bytes))
        if frame is None:
            return _cached_or_empty(
                state,
                now=now,
                source="secondary_decode_cache",
                reason="secondary frame decode failed",
                stream_ts=stream_ts,
            )
        try:
            timeout_s = 1.0 if min_interval_s <= 1.3 else 0.85
            data = await asyncio.wait_for(
                _await_maybe(deps.detect_secondary_frame(vision, frame)),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            return _cached_or_empty(
                state,
                now=now,
                source="secondary_timeout_cache",
                reason="secondary detection timeout",
                stream_ts=stream_ts,
            )
        except Exception:
            return _cached_or_empty(
                state,
                now=now,
                source="secondary_error_cache",
                reason="secondary detection failed",
                stream_ts=stream_ts,
            )
        if not isinstance(data, dict):
            data = {
                "detections": [],
                "frame": {"width": None, "height": None},
                "ts": 0.0,
            }
        data["stream_ts"] = float(stream_ts or 0.0)
        return state.finalize_fresh_payload(
            data,
            refreshed_at=float(deps.now()),
            stream_ts=stream_ts,
        )
