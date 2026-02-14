#!/usr/bin/env python3
"""Didier MVP vision worker service (multiprocessing-first)."""

from __future__ import annotations

import multiprocessing as mp
import os
import time
import sys
import threading
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.hailo.monitor import detect_hailo

VISION_HOST = os.getenv("DIDIER_VISION_HOST", "127.0.0.1")
VISION_PORT = int(os.getenv("DIDIER_VISION_PORT", "5011"))
TARGET_FPS = float(os.getenv("DIDIER_VISION_FPS", "30"))
METRICS_MIN_INTERVAL_S = float(os.getenv("DIDIER_VISION_METRICS_MIN_INTERVAL_S", "0.5"))
APP_STARTED_AT = time.time()

app = FastAPI(title="Didier MVP Vision", version="0.1.0")

_ctx = mp.get_context("spawn")
_manager: Any | None = None
_shared: Any | None = None
_stop_event: Any | None = None
_worker: mp.Process | None = None
_metrics_lock = threading.Lock()
_metrics_last_ts = 0.0
_metrics_last_payload: dict[str, Any] | None = None


def _vision_loop(shared: Any, stop_event: Any, fps: float) -> None:
    started = time.time()
    mode = "hailo_mode" if detect_hailo() else "cpu_mode"
    shared["mode"] = mode
    shared["worker_started_at"] = started
    frame_period = 1.0 / max(fps, 1.0)
    frames = 0
    while not stop_event.is_set():
        loop_start = time.time()
        frames += 1
        elapsed = max(loop_start - started, 1e-6)
        shared["frames"] = frames
        shared["fps"] = frames / elapsed
        shared["last_frame_ts"] = loop_start
        sleep_s = frame_period - (time.time() - loop_start)
        if sleep_s > 0:
            time.sleep(sleep_s)


@app.on_event("startup")
async def _startup() -> None:
    global _worker, _manager, _shared, _stop_event
    _manager = _ctx.Manager()
    _shared = _manager.dict(
        {
            "mode": "init",
            "frames": 0,
            "fps": 0.0,
            "last_frame_ts": 0.0,
            "worker_started_at": 0.0,
        }
    )
    _stop_event = _ctx.Event()
    _stop_event.clear()
    _worker = _ctx.Process(
        target=_vision_loop,
        args=(_shared, _stop_event, TARGET_FPS),
        daemon=True,
        name="didier-vision-worker",
    )
    _worker.start()


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _stop_event:
        _stop_event.set()
    if _worker and _worker.is_alive():
        _worker.join(timeout=2.0)


@app.get("/health")
async def health() -> dict[str, Any]:
    alive = bool(_worker and _worker.is_alive())
    mode = _shared.get("mode", "init") if _shared is not None else "init"
    return {
        "status": "ok" if alive else "degraded",
        "service": "didier-vision",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "detail": mode if alive else "worker_down",
        "worker_alive": alive,
        "mode": mode,
    }


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    global _metrics_last_ts, _metrics_last_payload
    now = time.time()
    with _metrics_lock:
        if (
            _metrics_last_payload is not None
            and (now - _metrics_last_ts) < max(METRICS_MIN_INTERVAL_S, 0.0)
        ):
            return dict(_metrics_last_payload)

        last_ts = float(_shared.get("last_frame_ts", 0.0) or 0.0) if _shared is not None else 0.0
        age_s = None if last_ts <= 0 else round(max(now - last_ts, 0.0), 3)
        payload = {
            "service": "didier-vision",
            "uptime_s": round(time.time() - APP_STARTED_AT, 3),
            "ts": now,
            "frames": int(_shared.get("frames", 0) or 0) if _shared is not None else 0,
            "fps": round(float(_shared.get("fps", 0.0) or 0.0), 2) if _shared is not None else 0.0,
            "last_frame_age_s": age_s,
            "mode": _shared.get("mode", "init") if _shared is not None else "init",
        }
        _metrics_last_payload = payload
        _metrics_last_ts = now
        return dict(payload)


@app.get("/vision/status-secondary")
async def status_secondary() -> dict[str, Any]:
    alive = bool(_worker and _worker.is_alive())
    mode = _shared.get("mode", "init") if _shared is not None else "init"
    return {
        "status": "ok" if alive else "degraded",
        "service": "didier-vision",
        "ts": time.time(),
        "detail": "secondary_ready" if alive else "worker_down",
        "mode": mode,
    }


@app.get("/infer")
async def infer() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": _shared.get("mode", "init") if _shared is not None else "init",
        "detections": [],
        "ts": time.time(),
    }


def main() -> int:
    uvicorn.run(app, host=VISION_HOST, port=VISION_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
