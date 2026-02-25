#!/usr/bin/env python3
"""Didier MVP vision worker service (multiprocessing-first)."""

from __future__ import annotations

import asyncio
import logging
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
from core.hailo.tappas_pipeline import TappasPipeline
from core.shared_state import update_worker_metrics
from shared.ipc import request as ipc_request

VISION_HOST = os.getenv("DIDIER_VISION_HOST", "127.0.0.1")
VISION_PORT = int(os.getenv("DIDIER_VISION_PORT", "5011"))
TARGET_FPS = float(os.getenv("DIDIER_VISION_FPS", "30"))
VISION_SOCKET_PATH = os.getenv("DIDIER_VISION_SOCK", "/tmp/didier_vision.sock").strip()
METRICS_MIN_INTERVAL_S = float(os.getenv("DIDIER_VISION_METRICS_MIN_INTERVAL_S", "0.5"))
VISION_SHARED_STATE_INTERVAL_S = max(
    0.5, min(float(os.getenv("DIDIER_VISION_SHARED_STATE_INTERVAL_S", "1.0")), 5.0)
)
VISION_TAPPAS_RESTART_INTERVAL_S = max(
    2.0, min(float(os.getenv("DIDIER_VISION_TAPPAS_RESTART_INTERVAL_S", "6.0")), 30.0)
)
VISION_ENABLE_TAPPAS = os.getenv("DIDIER_VISION_ENABLE_TAPPAS", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
VISION_SEE_MAX_AGE_S = float(os.getenv("DIDIER_VISION_SEE_MAX_AGE_S", "2.5"))
VISION_SEE_OWNER_CHECK = os.getenv("DIDIER_VISION_SEE_OWNER_CHECK", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
VISION_SEE_OWNER_TIMEOUT_S = max(0.2, min(float(os.getenv("DIDIER_VISION_SEE_OWNER_TIMEOUT_S", "0.8")), 2.5))
VISION_ROOM_HINT = os.getenv("DIDIER_VISION_ROOM_HINT", "").strip()
APP_STARTED_AT = time.time()
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = FastAPI(title="Didier MVP Vision", version="0.1.0")

_ctx = mp.get_context("spawn")
_manager: Any | None = None
_shared: Any | None = None
_stop_event: Any | None = None
_worker: mp.Process | None = None
_metrics_lock = threading.Lock()
_metrics_last_ts = 0.0
_metrics_last_payload: dict[str, Any] | None = None
_tappas: TappasPipeline | None = None
_tappas_task: asyncio.Task[None] | None = None
_shared_state_task: asyncio.Task[None] | None = None
_last_tappas_restart_ts = 0.0


def _vision_loop(shared: Any, stop_event: Any, fps: float, initial_mode: str) -> None:
    started = time.time()
    mode = initial_mode
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


async def _poll_tappas_status() -> None:
    global _last_tappas_restart_ts
    while True:
        if _shared is not None and _tappas is not None:
            status = _tappas.status()
            _shared["tappas"] = status
            if _tappas.enabled and not bool(status.get("started", False)):
                now = time.time()
                if (now - _last_tappas_restart_ts) >= VISION_TAPPAS_RESTART_INTERVAL_S:
                    _last_tappas_restart_ts = now
                    _tappas.start()
                    _shared["tappas"] = _tappas.status()
        await asyncio.sleep(1.0)


async def _publish_shared_state_loop() -> None:
    while True:
        now = time.time()
        alive = bool(_worker and _worker.is_alive())
        last_ts = float(_shared.get("last_frame_ts", 0.0) or 0.0) if _shared is not None else 0.0
        age_s = None if last_ts <= 0 else round(max(now - last_ts, 0.0), 3)
        payload = {
            "status": "ok" if alive else "degraded",
            "service": "didier-vision",
            "uptime_s": round(now - APP_STARTED_AT, 3),
            "mode": _shared.get("mode", "init") if _shared is not None else "init",
            "frames": int(_shared.get("frames", 0) or 0) if _shared is not None else 0,
            "fps": round(float(_shared.get("fps", 0.0) or 0.0), 2) if _shared is not None else 0.0,
            "last_frame_age_s": age_s,
        }
        await asyncio.to_thread(update_worker_metrics, "vision", payload)
        await asyncio.sleep(VISION_SHARED_STATE_INTERVAL_S)


def _cleanup_socket(socket_path: str) -> None:
    if not socket_path:
        return
    try:
        path = Path(socket_path)
        if path.exists():
            path.unlink()
    except Exception:
        pass


@app.on_event("startup")
async def _startup() -> None:
    global _worker, _manager, _shared, _stop_event, _tappas, _tappas_task, _shared_state_task
    logging.basicConfig(
        level=os.getenv("DIDIER_LOG_LEVEL", "INFO").upper(),
        format=LOG_FORMAT,
    )
    # pyHailoRT emits a deprecation warning on every frame activation; keep logs usable.
    logging.getLogger("pyhailort").setLevel(logging.ERROR)
    logging.getLogger("hailo_platform").setLevel(logging.ERROR)
    _manager = _ctx.Manager()
    _shared = _manager.dict(
        {
            "mode": "init",
            "frames": 0,
            "fps": 0.0,
            "last_frame_ts": 0.0,
            "worker_started_at": 0.0,
            "tappas": {},
        }
    )
    _stop_event = _ctx.Event()
    _stop_event.clear()
    _tappas = TappasPipeline() if VISION_ENABLE_TAPPAS else None
    _tappas_started = bool(_tappas and _tappas.start())
    worker_mode = "hailo_mode" if _tappas_started else "cpu_mode"
    _shared["mode"] = worker_mode
    _worker = _ctx.Process(
        target=_vision_loop,
        args=(_shared, _stop_event, TARGET_FPS, worker_mode),
        daemon=True,
        name="didier-vision-worker",
    )
    _worker.start()
    if _tappas is not None:
        _shared["tappas"] = _tappas.status()
        _tappas_task = asyncio.create_task(_poll_tappas_status())
    else:
        _shared["tappas"] = {
            "backend": "disabled",
            "enabled": False,
            "started": False,
            "frames_seen": 0,
            "command": None,
            "uptime_s": 0.0,
            "last_error": "disabled_by_config",
        }
    _shared_state_task = asyncio.create_task(_publish_shared_state_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _tappas_task, _shared_state_task
    if _stop_event:
        _stop_event.set()
    if _worker and _worker.is_alive():
        _worker.join(timeout=2.0)
    if _tappas_task is not None:
        _tappas_task.cancel()
        try:
            await _tappas_task
        except asyncio.CancelledError:
            pass
        _tappas_task = None
    if _shared_state_task is not None:
        _shared_state_task.cancel()
        try:
            await _shared_state_task
        except asyncio.CancelledError:
            pass
        _shared_state_task = None
    if _tappas is not None:
        _tappas.stop()
    _cleanup_socket(VISION_SOCKET_PATH)


@app.get("/health")
async def health() -> dict[str, Any]:
    alive = bool(_worker and _worker.is_alive())
    mode = _shared.get("mode", "init") if _shared is not None else "init"
    tappas = dict(_shared.get("tappas", {})) if _shared is not None else {}
    if tappas.get("started"):
        mode = "hailo_mode"
    return {
        "status": "ok" if alive else "degraded",
        "service": "didier-vision",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "detail": mode if alive else "worker_down",
        "worker_alive": alive,
        "mode": mode,
        "tappas": tappas,
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
            "tappas": dict(_shared.get("tappas", {})) if _shared is not None else {},
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


@app.get("/vision/see_user")
async def see_user() -> dict[str, Any]:
    alive = bool(_worker and _worker.is_alive())
    now = time.time()
    last_ts = float(_shared.get("last_frame_ts", 0.0) or 0.0) if _shared is not None else 0.0
    age_s = None if last_ts <= 0 else round(max(now - last_ts, 0.0), 3)
    seen = bool(alive and age_s is not None and age_s <= max(VISION_SEE_MAX_AGE_S, 0.3))

    owner_check: dict[str, Any] | None = None
    if seen and VISION_SEE_OWNER_CHECK:
        try:
            response = await ipc_request(
                "GET",
                "/vision/owner",
                service="api",
                timeout=VISION_SEE_OWNER_TIMEOUT_S,
            )
            if response.is_success:
                data = response.json()
                if isinstance(data, dict):
                    owner_check = {
                        "ok": bool(data.get("ok", False)),
                        "enrolled": bool(data.get("enrolled", False)),
                        "match": data.get("match"),
                        "method": data.get("method"),
                    }
        except Exception:
            owner_check = None

    location = VISION_ROOM_HINT or "inconnue"
    if not seen:
        summary = "Je ne te vois pas clairement pour l'instant."
    elif owner_check and owner_check.get("ok") and owner_check.get("enrolled"):
        if owner_check.get("match") is True:
            summary = f"Je te vois bien dans {location}." if VISION_ROOM_HINT else "Je te vois bien devant la camera."
        else:
            summary = "Je vois quelqu'un devant la camera."
    else:
        summary = f"Je te vois dans {location}." if VISION_ROOM_HINT else "Je te vois bien devant la camera."

    return {
        "status": "ok" if alive else "degraded",
        "service": "didier-vision",
        "uptime_s": round(now - APP_STARTED_AT, 3),
        "ts": now,
        "detail": "user_visible" if seen else "user_not_visible",
        "seen": seen,
        "location": location,
        "last_frame_age_s": age_s,
        "owner_check": owner_check,
        "summary": summary,
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
    if VISION_SOCKET_PATH:
        try:
            Path(VISION_SOCKET_PATH).unlink(missing_ok=True)
        except Exception:
            pass
        uvicorn.run(app, uds=VISION_SOCKET_PATH, log_level="info")
    else:
        uvicorn.run(app, host=VISION_HOST, port=VISION_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
