#!/usr/bin/env python3
"""Didier MVP brain service (local LLM bridge with safe stub fallback)."""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.microgpt_lite import MicroGPTLite
from core.shared_state import update_worker_metrics
from shared.ipc import request as ipc_request

BRAIN_HOST = os.getenv("DIDIER_BRAIN_HOST", "127.0.0.1")
BRAIN_PORT = int(os.getenv("DIDIER_BRAIN_PORT", "5012"))
OLLAMA_BASE_URL = os.getenv("DIDIER_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_UNIX_SOCKET = os.getenv("DIDIER_OLLAMA_UNIX_SOCKET", "").strip()
DEFAULT_MODEL = os.getenv("DIDIER_BRAIN_MODEL", "llama3.2:3b")
MICRO_BRAIN_ENABLED = os.getenv("DIDIER_MICRO_BRAIN_ENABLED", "1").strip().lower() not in {
    "0",
    "false",
    "no",
    "off",
}
MICRO_POLL_S = float(os.getenv("DIDIER_MICRO_POLL_S", "1.0"))
APP_STARTED_AT = time.time()

brain_state: dict[str, Any] = {
    "ollama_up": False,
    "last_check_ts": 0.0,
    "last_error": None,
    "ollama_mode": "tcp",
    "ollama_socket": None,
    "ollama_url": OLLAMA_BASE_URL,
    "workers": {"api": False, "vision": False, "audio": False},
    "micro": {"enabled": MICRO_BRAIN_ENABLED},
    "last_generate_ms": 0.0,
    "response_p95_ms": 0.0,
}

app = FastAPI(title="Didier MVP Brain", version="0.1.0")
_micro_brain = MicroGPTLite() if MICRO_BRAIN_ENABLED else None
_recent_generate_ms: list[float] = []
_shared_state_task: asyncio.Task[None] | None = None


async def _fetch_worker_ok(service: str, path: str = "/health") -> bool:
    try:
        res = await ipc_request("GET", path, service=service, timeout=1.0)
        if not res.is_success:
            return False
        try:
            data = res.json()
        except Exception:
            return True
        status = str(data.get("status", "")).lower()
        if not status:
            return True
        return status == "ok"
    except Exception:
        return False


def _resolve_ollama_socket() -> str | None:
    candidates: list[str] = []
    if OLLAMA_UNIX_SOCKET:
        candidates.append(OLLAMA_UNIX_SOCKET)
    candidates.extend(
        [
            "/run/ollama/ollama.sock",
            "/var/run/ollama.sock",
            "/tmp/ollama.sock",
        ]
    )
    for candidate in candidates:
        if not candidate:
            continue
        if Path(candidate).exists():
            return candidate
    return None


async def _ollama_request(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> httpx.Response:
    socket_path = _resolve_ollama_socket()
    if socket_path:
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(
            base_url="http://localhost",
            transport=transport,
            timeout=timeout,
        ) as client:
            brain_state["ollama_mode"] = "unix"
            brain_state["ollama_socket"] = socket_path
            brain_state["ollama_url"] = OLLAMA_BASE_URL
            return await client.request(method, path, json=payload)
    async with httpx.AsyncClient(timeout=timeout) as client:
        brain_state["ollama_mode"] = "tcp"
        brain_state["ollama_socket"] = None
        brain_state["ollama_url"] = OLLAMA_BASE_URL
        return await client.request(method, f"{OLLAMA_BASE_URL}{path}", json=payload)


async def _check_ollama_once() -> None:
    try:
        res = await _ollama_request("GET", "/api/tags", timeout=2.0)
        brain_state["ollama_up"] = res.is_success
        brain_state["last_error"] = None if res.is_success else f"http {res.status_code}"
    except Exception as exc:  # pragma: no cover
        brain_state["ollama_up"] = False
        brain_state["last_error"] = str(exc)
    finally:
        brain_state["last_check_ts"] = time.time()


async def _poll_ollama_loop() -> None:
    while True:
        await _check_ollama_once()
        await asyncio.sleep(2.0)


def _update_latency_stats(latency_ms: float) -> None:
    _recent_generate_ms.append(float(latency_ms))
    if len(_recent_generate_ms) > 64:
        del _recent_generate_ms[:-64]
    ordered = sorted(_recent_generate_ms)
    if not ordered:
        brain_state["response_p95_ms"] = 0.0
        return
    idx = max(0, int((len(ordered) - 1) * 0.95))
    brain_state["response_p95_ms"] = float(ordered[idx])


async def _poll_micro_loop() -> None:
    while True:
        api_ok, vision_ok, audio_ok = await asyncio.gather(
            _fetch_worker_ok("api", "/metrics"),
            _fetch_worker_ok("vision", "/health"),
            _fetch_worker_ok("audio", "/health"),
        )
        workers = {"api": api_ok, "vision": vision_ok, "audio": audio_ok}
        brain_state["workers"] = workers
        if _micro_brain is not None:
            try:
                load1 = os.getloadavg()[0]
            except Exception:
                load1 = 0.0
            _micro_brain.ingest(
                {
                    "load1": float(load1),
                    "workers": workers,
                    "response_p95_ms": float(brain_state.get("response_p95_ms", 0.0) or 0.0),
                }
            )
            brain_state["micro"] = {
                "enabled": True,
                **_micro_brain.status(),
            }
        await asyncio.sleep(max(MICRO_POLL_S, 0.5))


async def _publish_shared_state_loop() -> None:
    while True:
        payload = {
            "status": "ok" if bool(brain_state["ollama_up"]) else "degraded",
            "service": "didier-brain",
            "uptime_s": round(time.time() - APP_STARTED_AT, 3),
            "detail": "ollama_up" if bool(brain_state["ollama_up"]) else (brain_state["last_error"] or "ollama_unavailable"),
            "ollama_up": bool(brain_state["ollama_up"]),
            "workers": dict(brain_state.get("workers", {})),
            "last_generate_ms": float(brain_state.get("last_generate_ms", 0.0) or 0.0),
        }
        await asyncio.to_thread(update_worker_metrics, "brain", payload)
        await asyncio.sleep(0.5)


@app.on_event("startup")
async def _startup() -> None:
    global _shared_state_task
    asyncio.create_task(_poll_ollama_loop())
    if MICRO_BRAIN_ENABLED:
        asyncio.create_task(_poll_micro_loop())
    _shared_state_task = asyncio.create_task(_publish_shared_state_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _shared_state_task
    if _shared_state_task is not None:
        _shared_state_task.cancel()
        try:
            await _shared_state_task
        except asyncio.CancelledError:
            pass
        _shared_state_task = None


@app.get("/health")
async def health() -> dict[str, Any]:
    healthy = bool(brain_state["ollama_up"])
    if MICRO_BRAIN_ENABLED and _micro_brain is not None:
        micro_score = int(_micro_brain.status().get("latest_score", 0) or 0)
    else:
        micro_score = 0
    return {
        "status": "ok" if healthy else "degraded",
        "service": "didier-brain",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "detail": "ollama_up" if healthy else (brain_state["last_error"] or "ollama_unavailable"),
        "ollama_up": healthy,
        "ollama_mode": brain_state["ollama_mode"],
        "ollama_socket": brain_state["ollama_socket"],
        "workers": brain_state["workers"],
        "micro_score": micro_score,
    }


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    return {
        "service": "didier-brain",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "ollama_up": bool(brain_state["ollama_up"]),
        "ollama_mode": brain_state["ollama_mode"],
        "ollama_socket": brain_state["ollama_socket"],
        "ollama_url": brain_state["ollama_url"],
        "last_check_ts": brain_state["last_check_ts"],
        "last_error": brain_state["last_error"],
        "workers": brain_state["workers"],
        "micro": brain_state["micro"],
        "last_generate_ms": brain_state["last_generate_ms"],
        "response_p95_ms": brain_state["response_p95_ms"],
    }


@app.get("/micro/status")
async def micro_status() -> dict[str, Any]:
    if _micro_brain is None:
        return {"enabled": False}
    return {"enabled": True, **_micro_brain.status()}


@app.post("/generate")
async def generate(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")

    model = str(payload.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    if MICRO_BRAIN_ENABLED and _micro_brain is not None:
        decision = _micro_brain.decide(prompt, {"workers": brain_state.get("workers", {})})
        if not decision.wake_ollama and decision.quick_response:
            elapsed_ms = (time.time() - started) * 1000.0
            brain_state["last_generate_ms"] = round(elapsed_ms, 2)
            _update_latency_stats(elapsed_ms)
            return {
                "status": "micro",
                "model": "microgpt-lite",
                "response": decision.quick_response,
                "reason": decision.reason,
            }

    if not brain_state["ollama_up"]:
        elapsed_ms = (time.time() - started) * 1000.0
        brain_state["last_generate_ms"] = round(elapsed_ms, 2)
        _update_latency_stats(elapsed_ms)
        return {
            "status": "stub",
            "model": "stub",
            "response": f"[stub] {prompt[:120]}",
        }

    req_payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 128},
    }
    try:
        res = await _ollama_request(
            "POST",
            "/api/generate",
            payload=req_payload,
            timeout=20.0,
        )
        res.raise_for_status()
        data = res.json()
    except Exception as exc:
        elapsed_ms = (time.time() - started) * 1000.0
        brain_state["last_generate_ms"] = round(elapsed_ms, 2)
        _update_latency_stats(elapsed_ms)
        return {
            "status": "stub",
            "model": "stub",
            "response": f"[stub-fallback] {prompt[:120]}",
            "error": str(exc),
        }
    elapsed_ms = (time.time() - started) * 1000.0
    brain_state["last_generate_ms"] = round(elapsed_ms, 2)
    _update_latency_stats(elapsed_ms)
    return {
        "status": "ok",
        "model": model,
        "response": str(data.get("response", "")).strip(),
    }


def main() -> int:
    socket_path = os.getenv("DIDIER_BRAIN_SOCK", "/tmp/didier_brain.sock").strip()
    if socket_path:
        try:
            Path(socket_path).unlink(missing_ok=True)
        except Exception:
            pass
        uvicorn.run(app, uds=socket_path, log_level="info")
    else:
        uvicorn.run(app, host=BRAIN_HOST, port=BRAIN_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
