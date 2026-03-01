"""Helpers for passive remote stream status evaluation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RemoteStreamSnapshot:
    present: bool
    ts: float = 0.0
    fps: int | None = None
    frame_gap_s: float | None = None
    last_error: str | None = None
    alive: bool = False
    started: bool = False
    waiting_s: float | None = None
    spawn_count: int = 0
    restart_count: int = 0
    input_url: str | None = None


def snapshot_remote_stream(stream: Any) -> RemoteStreamSnapshot:
    if stream is None:
        return RemoteStreamSnapshot(present=False, ts=0.0)
    _frame, ts = stream.get_last()
    fps = None
    frame_gap_s = None
    last_error = None
    alive = False
    started = False
    waiting_s = None
    spawn_count = 0
    restart_count = 0
    input_url = None
    if hasattr(stream, "debug_snapshot"):
        try:
            debug = stream.debug_snapshot()
        except Exception:
            debug = None
        if isinstance(debug, dict):
            fps_raw = debug.get("fps")
            try:
                fps = int(fps_raw) if fps_raw is not None else None
            except Exception:
                fps = None
            gap_raw = debug.get("frame_gap_s")
            try:
                frame_gap_s = float(gap_raw) if gap_raw is not None else None
            except Exception:
                frame_gap_s = None
            err_raw = debug.get("last_error")
            last_error = str(err_raw).strip() if err_raw else None
            alive = bool(debug.get("alive"))
            started = bool(debug.get("started_at"))
            wait_raw = debug.get("waiting_s")
            try:
                waiting_s = float(wait_raw) if wait_raw is not None else None
            except Exception:
                waiting_s = None
            spawn_raw = debug.get("spawn_count")
            try:
                spawn_count = int(spawn_raw) if spawn_raw is not None else 0
            except Exception:
                spawn_count = 0
            restart_raw = debug.get("restart_count")
            try:
                restart_count = int(restart_raw) if restart_raw is not None else 0
            except Exception:
                restart_count = 0
            url_raw = debug.get("input_url")
            input_url = str(url_raw).strip() if url_raw else None
    return RemoteStreamSnapshot(
        present=True,
        ts=float(ts or 0.0),
        fps=fps,
        frame_gap_s=frame_gap_s,
        last_error=last_error,
        alive=alive,
        started=started,
        waiting_s=waiting_s,
        spawn_count=spawn_count,
        restart_count=restart_count,
        input_url=input_url,
    )


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
            "fps": None,
            "frame_gap_s": None,
            "last_error": None,
            "stalled": False,
            "alive": False,
            "started": False,
            "waiting_s": None,
            "spawn_count": 0,
            "restart_count": 0,
            "input_url": None,
            "diagnostic": "stream_not_started",
        }
    ts = float(snapshot.ts or 0.0)
    age_s = max(0.0, float(now) - ts) if ts > 0.0 else None
    is_online = bool(ts > 0.0 and age_s is not None and age_s < float(stale_after_s))
    if not snapshot.started:
        diagnostic = "stream_not_started"
    elif is_online:
        diagnostic = "healthy"
    elif snapshot.last_error == "waiting for source frames":
        diagnostic = "source_waiting"
    elif snapshot.last_error == "ffmpeg stream stalled":
        diagnostic = "source_stalled"
    elif snapshot.last_error == "ffmpeg stream restart":
        diagnostic = "restarting"
    elif bool(ts > 0.0 and age_s is not None and age_s >= float(stale_after_s)):
        diagnostic = "stale_frame"
    elif snapshot.alive:
        diagnostic = "degraded"
    else:
        diagnostic = "reader_down"
    return {
        "status": "online" if is_online else "offline",
        "age_s": round(age_s, 1) if age_s is not None else None,
        "ts": ts,
        "fps": snapshot.fps,
        "frame_gap_s": snapshot.frame_gap_s,
        "last_error": snapshot.last_error,
        "stalled": bool(ts > 0.0 and age_s is not None and age_s >= float(stale_after_s)),
        "alive": snapshot.alive,
        "started": snapshot.started,
        "waiting_s": round(snapshot.waiting_s, 1) if snapshot.waiting_s is not None else None,
        "spawn_count": snapshot.spawn_count,
        "restart_count": snapshot.restart_count,
        "input_url": snapshot.input_url,
        "diagnostic": diagnostic,
    }
