"""Native OpenClaw IPC bridge served over Unix socket."""

from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import FastAPI, HTTPException

from core.shared_state import openclaw_state_snapshot
from core.shared_state import write_openclaw_memory
from orchestrator.openclaw_bridge import get_openclaw_bridge

app = FastAPI(title="Didier OpenClaw Native IPC Bridge")


@app.get("/health")
async def health() -> dict[str, Any]:
    bridge = get_openclaw_bridge()
    status = await asyncio.to_thread(bridge.status)
    running = bool(status.get("running", False))
    return {
        "status": "ok" if running else "degraded",
        "service": "didier-openclaw-bridge",
        "uptime_s": float(status.get("uptime_s", 0.0) or 0.0),
        "ts": time.time(),
        "detail": status,
    }


@app.post("/react")
async def react(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    timeout_s = max(0.5, min(float(payload.get("timeout_s", 3.0)), 12.0))
    bridge = get_openclaw_bridge()
    result = await asyncio.to_thread(
        bridge.relay_prompt,
        prompt,
        agent_id=str(payload.get("agent_id", "")).strip() or None,
        session_key=str(payload.get("session_key", "")).strip() or None,
        wake_mode=str(payload.get("wake_mode", "now")).strip() or "now",
        timeout_s=timeout_s,
    )
    if not isinstance(result, dict):
        return {"ok": False, "error": "invalid_bridge_result"}
    return result


@app.get("/metrics")
async def metrics(timeout_s: float = 4.0) -> dict[str, Any]:
    timeout_s = max(0.5, min(float(timeout_s), 12.0))
    bridge = get_openclaw_bridge()
    result = await asyncio.to_thread(bridge.metrics, timeout_s)
    if isinstance(result, dict) and result.get("ok", False):
        return result
    status = await asyncio.to_thread(bridge.status)
    if bool(status.get("running", False)):
        # Keep the API responsive even when deep OpenClaw health RPC is slow.
        return {
            "ok": True,
            "degraded": True,
            "error": (result or {}).get("error", "openclaw metrics timeout")
            if isinstance(result, dict)
            else "openclaw metrics timeout",
            "status": status,
            "shared_state": await asyncio.to_thread(bridge.shared_state_snapshot),
        }
    if not isinstance(result, dict):
        return {"ok": False, "error": "invalid_bridge_metrics"}
    return result


@app.get("/tasks")
async def tasks() -> dict[str, Any]:
    bridge = get_openclaw_bridge()
    return await asyncio.to_thread(bridge.tasks)


@app.get("/memory")
async def memory(include_content: bool = False) -> dict[str, Any]:
    snap = await asyncio.to_thread(openclaw_state_snapshot, bool(include_content))
    return {"ok": True, "shared_state": snap}


@app.post("/memory")
async def memory_write(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path = str(payload.get("path", "")).strip()
    content = str(payload.get("content", ""))
    append = bool(payload.get("append", False))
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    try:
        entry = await asyncio.to_thread(write_openclaw_memory, path, content, append)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "ok": True,
        "entry": entry,
        "shared_state": await asyncio.to_thread(openclaw_state_snapshot),
    }
