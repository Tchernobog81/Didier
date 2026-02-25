"""Resilience guards for API routes."""

from __future__ import annotations

import functools
import threading
import time
from typing import Any, Awaitable, Callable, TypeVar

from fastapi import HTTPException

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])

_LOCK = threading.Lock()
_STATE: dict[str, dict[str, float | int]] = {}


def _state_for(name: str) -> dict[str, float | int]:
    with _LOCK:
        if name not in _STATE:
            _STATE[name] = {"failures": 0, "opened_until": 0.0}
        return _STATE[name]


def _record_success(name: str) -> None:
    state = _state_for(name)
    with _LOCK:
        state["failures"] = 0
        state["opened_until"] = 0.0


def _record_failure(name: str, failure_threshold: int, reset_timeout_s: float) -> None:
    now = time.monotonic()
    state = _state_for(name)
    with _LOCK:
        failures = int(state["failures"]) + 1
        state["failures"] = failures
        if failures >= failure_threshold:
            state["opened_until"] = now + reset_timeout_s


def circuit_breaker(
    name: str,
    *,
    failure_threshold: int = 3,
    reset_timeout_s: float = 30.0,
) -> Callable[[F], F]:
    """Open route circuit after N consecutive failures."""

    failure_threshold = max(1, int(failure_threshold))
    reset_timeout_s = max(1.0, float(reset_timeout_s))

    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            now = time.monotonic()
            state = _state_for(name)
            with _LOCK:
                opened_until = float(state["opened_until"])
            if opened_until > now:
                retry_after = max(1, int(opened_until - now))
                raise HTTPException(
                    status_code=503,
                    detail=f"circuit_open:{name}",
                    headers={"Retry-After": str(retry_after)},
                )
            try:
                result = await func(*args, **kwargs)
            except HTTPException as exc:
                if exc.status_code >= 500:
                    _record_failure(name, failure_threshold, reset_timeout_s)
                raise
            except Exception:
                _record_failure(name, failure_threshold, reset_timeout_s)
                raise
            _record_success(name)
            return result

        return wrapped  # type: ignore[return-value]

    return decorator
