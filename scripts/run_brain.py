#!/usr/bin/env python3
"""Didier MVP brain service (local LLM bridge with safe stub fallback)."""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException

BRAIN_HOST = os.getenv("DIDIER_BRAIN_HOST", "127.0.0.1")
BRAIN_PORT = int(os.getenv("DIDIER_BRAIN_PORT", "5012"))
OLLAMA_BASE_URL = os.getenv("DIDIER_OLLAMA_BASE_URL", "http://127.0.0.1:11435")
OLLAMA_UNIX_SOCKET = os.getenv("DIDIER_OLLAMA_UNIX_SOCKET", "").strip()
DEFAULT_MODEL = os.getenv("DIDIER_BRAIN_MODEL", "llama3.2:1b")
APP_STARTED_AT = time.time()

brain_state: dict[str, Any] = {
    "ollama_up": False,
    "last_check_ts": 0.0,
    "last_error": None,
    "ollama_mode": "tcp",
    "ollama_socket": None,
    "ollama_url": OLLAMA_BASE_URL,
}

app = FastAPI(title="Didier MVP Brain", version="0.1.0")


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


@app.on_event("startup")
async def _startup() -> None:
    asyncio.create_task(_poll_ollama_loop())


@app.get("/health")
async def health() -> dict[str, Any]:
    healthy = bool(brain_state["ollama_up"])
    return {
        "status": "ok" if healthy else "degraded",
        "service": "didier-brain",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "detail": "ollama_up" if healthy else (brain_state["last_error"] or "ollama_unavailable"),
        "ollama_up": healthy,
        "ollama_mode": brain_state["ollama_mode"],
        "ollama_socket": brain_state["ollama_socket"],
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
    }


@app.post("/generate")
async def generate(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")

    model = str(payload.get("model", DEFAULT_MODEL)).strip() or DEFAULT_MODEL
    if not brain_state["ollama_up"]:
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
        return {
            "status": "stub",
            "model": "stub",
            "response": f"[stub-fallback] {prompt[:120]}",
            "error": str(exc),
        }
    return {
        "status": "ok",
        "model": model,
        "response": str(data.get("response", "")).strip(),
    }


def main() -> int:
    uvicorn.run(app, host=BRAIN_HOST, port=BRAIN_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
