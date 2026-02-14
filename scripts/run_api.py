#!/usr/bin/env python3
"""Didier MVP API service (lightweight control plane)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx
import psutil
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

APP_STARTED_AT = time.time()
API_HOST = os.getenv("DIDIER_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("DIDIER_API_PORT", "5010"))
VISION_BASE_URL = os.getenv("DIDIER_VISION_URL", "http://127.0.0.1:5011")
BRAIN_BASE_URL = os.getenv("DIDIER_BRAIN_URL", "http://127.0.0.1:5012")
AUDIO_BASE_URL = os.getenv("DIDIER_AUDIO_URL", "http://127.0.0.1:5013")
AUDIO_PROXY_TIMEOUT_S = float(os.getenv("DIDIER_AUDIO_PROXY_TIMEOUT_S", "1.5"))

WEB_DIR = Path("web")
INDEX_PATH = WEB_DIR / "index.html"

ACTUATORS: list[dict[str, str]] = [
    {"id": "camera_reconnect", "label": "Camera Reconnect"},
    {"id": "audio_beep", "label": "Audio Beep"},
    {"id": "vision_ping", "label": "Vision Ping"},
]

runtime_state: dict[str, Any] = {
    "vision": {"ok": False, "detail": "init"},
    "brain": {"ok": False, "detail": "init"},
    "audio": {"ok": False, "detail": "init"},
    "metrics": {"cpu_percent": 0.0, "mem_percent": 0.0, "rss_mb": 0.0},
}

app = FastAPI(title="Didier MVP API", version="0.1.0")
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


async def _fetch_health(base_url: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=1.5) as client:
            res = await client.get(f"{base_url}/health")
            if not res.is_success:
                return {"ok": False, "detail": f"http {res.status_code}"}
            payload = res.json()
            status = str(payload.get("status", "ok")).lower()
            detail = payload.get("detail") or payload.get("service") or payload.get("name") or status
            return {"ok": status == "ok", "detail": str(detail), "status": status}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "detail": str(exc)}


async def _poll_backends() -> None:
    while True:
        vision, brain, audio = await asyncio.gather(
            _fetch_health(VISION_BASE_URL),
            _fetch_health(BRAIN_BASE_URL),
            _fetch_health(AUDIO_BASE_URL),
        )
        runtime_state["vision"] = vision
        runtime_state["brain"] = brain
        runtime_state["audio"] = audio
        await asyncio.sleep(1.0)


async def _post_backend(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=AUDIO_PROXY_TIMEOUT_S) as client:
            res = await client.post(f"{AUDIO_BASE_URL}{path}", json=payload)
            if not res.is_success:
                detail = await read_backend_detail(res)
                raise HTTPException(status_code=res.status_code, detail=detail)
            return res.json()
    except HTTPException:
        raise
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=503, detail=str(exc))


async def read_backend_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
        detail = data.get("detail")
        if detail:
            return str(detail)
    except Exception:
        pass
    return f"http {response.status_code}"


async def _collect_metrics() -> None:
    proc = psutil.Process()
    while True:
        runtime_state["metrics"] = {
            "cpu_percent": float(psutil.cpu_percent(interval=None)),
            "mem_percent": float(psutil.virtual_memory().percent),
            "rss_mb": round(proc.memory_info().rss / (1024 * 1024), 2),
        }
        await asyncio.sleep(1.0)


@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_poll_backends())
    asyncio.create_task(_collect_metrics())


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    if INDEX_PATH.exists():
        return INDEX_PATH.read_text(encoding="utf-8")
    return "<h1>Didier MVP API</h1><p>Dashboard not found.</p>"


@app.get("/health")
async def health() -> dict[str, Any]:
    vision_ok = bool(runtime_state["vision"].get("ok"))
    brain_ok = bool(runtime_state["brain"].get("ok"))
    audio_ok = bool(runtime_state["audio"].get("ok"))
    overall_ok = vision_ok and brain_ok and audio_ok
    detail = "all_backends_ok" if overall_ok else {
        "vision": runtime_state["vision"].get("detail"),
        "brain": runtime_state["brain"].get("detail"),
        "audio": runtime_state["audio"].get("detail"),
    }
    return {
        "status": "ok" if overall_ok else "degraded",
        "service": "didier-api",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "detail": detail,
        "vision": runtime_state["vision"],
        "brain": runtime_state["brain"],
        "audio": runtime_state["audio"],
    }


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    return {
        "service": "didier-api",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "system": runtime_state["metrics"],
        "vision_ok": bool(runtime_state["vision"].get("ok")),
        "brain_ok": bool(runtime_state["brain"].get("ok")),
        "audio_ok": bool(runtime_state["audio"].get("ok")),
    }


@app.get("/actuators")
async def actuators() -> dict[str, Any]:
    return {"count": len(ACTUATORS), "items": ACTUATORS}


@app.post("/actuators/{actuator_id}")
async def actuator_trigger(actuator_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if actuator_id not in {item["id"] for item in ACTUATORS}:
        raise HTTPException(status_code=404, detail="unknown actuator")
    action = (payload or {}).get("action", "ping")
    if actuator_id == "audio_beep":
        result = await _post_backend("/beep", {})
        return {"status": "ok", "actuator": actuator_id, "action": action, "result": result}
    return {"status": "ok", "actuator": actuator_id, "action": action}


@app.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    result = await _post_backend("/speak", {"text": text})
    return {"status": "ok", "audio": result}


def main() -> int:
    uvicorn.run(app, host=API_HOST, port=API_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
