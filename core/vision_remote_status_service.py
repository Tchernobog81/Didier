"""Helpers for passive remote stream status evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RemoteStreamSnapshot:
    present: bool
    ts: float = 0.0


def snapshot_remote_stream(stream: Any) -> RemoteStreamSnapshot:
    if stream is None:
        return RemoteStreamSnapshot(present=False, ts=0.0)
    _frame, ts = stream.get_last()
    return RemoteStreamSnapshot(present=True, ts=float(ts or 0.0))


def evaluate_remote_stream_status(
    snapshot: RemoteStreamSnapshot,
    *,
    now: float,
    stale_after_s: float = 3.0,
) -> dict[str, Any]:
    if not snapshot.present:
        return {
            "status": "offline",
            "age_s": None,
            "ts": 0.0,
        }
    ts = float(snapshot.ts or 0.0)
    age_s = max(0.0, float(now) - ts) if ts > 0.0 else None
    is_online = bool(ts > 0.0 and age_s is not None and age_s < float(stale_after_s))
    return {
        "status": "online" if is_online else "offline",
        "age_s": round(age_s, 1) if age_s is not None else None,
        "ts": ts,
    }
