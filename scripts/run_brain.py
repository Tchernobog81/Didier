#!/usr/bin/env python3
"""Didier MVP brain service (local LLM bridge with safe stub fallback)."""

from __future__ import annotations

import asyncio
import logging
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
from core.backend_routing import choose_backend as choose_backend_contract
from core.ollama_targeting import is_local_ollama_url
from core.ollama_targeting import probe_ollama_endpoint
from core.ollama_targeting import resolve_pixel_ollama_base_url
from core.shared_state import read_state as read_shared_state
from core.shared_state import update_worker_metrics
from shared.ipc import request as ipc_request

BRAIN_HOST = os.getenv("DIDIER_BRAIN_HOST", "127.0.0.1")
BRAIN_PORT = int(os.getenv("DIDIER_BRAIN_PORT", "5012"))
BRAIN_SOCKET_PATH = os.getenv("DIDIER_BRAIN_SOCK", "/tmp/didier_brain.sock").strip()
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
BRAIN_SHARED_STATE_INTERVAL_S = max(
    0.5, min(float(os.getenv("DIDIER_BRAIN_SHARED_STATE_INTERVAL_S", "1.0")), 5.0)
)
DEFAULT_HTTP_TIMEOUT_S = 2.0
APP_STARTED_AT = time.time()
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

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
    "requests_total": 0,
    "micro_shortcuts": 0,
    "ollama_calls": 0,
    "stub_calls": 0,
    "last_routing": {
        "task_type": "chat",
        "preferred_backend": "local_ollama",
        "execution_backend": "local_ollama",
        "route_hint": "brain_local",
        "recommended_model": DEFAULT_MODEL,
    },
}

app = FastAPI(title="Didier MVP Brain", version="0.1.0")
_micro_brain = MicroGPTLite() if MICRO_BRAIN_ENABLED else None
_recent_generate_ms: list[float] = []
_shared_state_task: asyncio.Task[None] | None = None


async def _fetch_worker_ok(service: str, path: str = "/health") -> bool:
    try:
        res = await ipc_request("GET", path, service=service, timeout=DEFAULT_HTTP_TIMEOUT_S)
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
    timeout: float = DEFAULT_HTTP_TIMEOUT_S,
    base_url: str | None = None,
) -> httpx.Response:
    timeout = max(0.1, min(float(timeout), DEFAULT_HTTP_TIMEOUT_S))
    target_base = str(base_url or OLLAMA_BASE_URL).strip().rstrip("/")
    socket_path = _resolve_ollama_socket() if is_local_ollama_url(target_base) else None
    if socket_path and is_local_ollama_url(target_base):
        transport = httpx.AsyncHTTPTransport(uds=socket_path)
        async with httpx.AsyncClient(
            base_url="http://localhost",
            transport=transport,
            timeout=timeout,
        ) as client:
            brain_state["ollama_mode"] = "unix"
            brain_state["ollama_socket"] = socket_path
            brain_state["ollama_url"] = target_base
            return await client.request(method, path, json=payload)
    async with httpx.AsyncClient(timeout=timeout) as client:
        brain_state["ollama_mode"] = "tcp"
        brain_state["ollama_socket"] = None
        brain_state["ollama_url"] = target_base
        return await client.request(method, f"{target_base}{path}", json=payload)


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


def _http_error_brief(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        status = "unknown"
        detail = ""
        if exc.response is not None:
            status = str(exc.response.status_code)
            try:
                detail = str(exc.response.text or "").strip().replace("\n", " ")
            except Exception:
                detail = ""
        return f"HTTPStatusError:{status}:{detail[:120]}"
    return f"{type(exc).__name__}:{exc}"


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
            "micro_bypass_ratio": float(
                round(
                    (
                        (float(brain_state.get("micro_shortcuts", 0) or 0.0) * 100.0)
                        / max(1.0, float(brain_state.get("requests_total", 0) or 0.0))
                    ),
                    2,
                )
            ),
            "routing": dict(brain_state.get("last_routing", {})),
        }
        await asyncio.to_thread(update_worker_metrics, "brain", payload)
        await asyncio.sleep(BRAIN_SHARED_STATE_INTERVAL_S)


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
    global _shared_state_task
    logging.basicConfig(
        level=os.getenv("DIDIER_LOG_LEVEL", "INFO").upper(),
        format=LOG_FORMAT,
    )
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
    _cleanup_socket(BRAIN_SOCKET_PATH)


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
        "routing": brain_state.get("last_routing", {}),
    }


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    total_requests = int(brain_state.get("requests_total", 0) or 0)
    micro_shortcuts = int(brain_state.get("micro_shortcuts", 0) or 0)
    micro_bypass_ratio = round((micro_shortcuts * 100.0) / max(1, total_requests), 2)
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
        "requests_total": total_requests,
        "micro_shortcuts": micro_shortcuts,
        "ollama_calls": int(brain_state.get("ollama_calls", 0) or 0),
        "stub_calls": int(brain_state.get("stub_calls", 0) or 0),
        "micro_bypass_ratio": micro_bypass_ratio,
        "routing": brain_state.get("last_routing", {}),
    }


@app.get("/micro/status")
async def micro_status() -> dict[str, Any]:
    if _micro_brain is None:
        return {"enabled": False}
    return {"enabled": True, **_micro_brain.status()}


def choose_backend(
    prompt: str,
    task_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = {
        "workers": dict(brain_state.get("workers", {})),
        "response_p95_ms": float(brain_state.get("response_p95_ms", 0.0) or 0.0),
        "voice_request": bool((payload or {}).get("is_voice", False)),
    }
    if isinstance(payload, dict):
        context.update(payload)
    return choose_backend_contract(prompt, task_type, context=context)


async def _list_ollama_models(base_url: str | None = None) -> list[str]:
    try:
        response = await _ollama_request("GET", "/api/tags", timeout=2.0, base_url=base_url)
    except Exception:
        return []
    if not response.is_success:
        return []
    try:
        payload = response.json()
    except Exception:
        return []
    models: list[str] = []
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        if not isinstance(item, dict):
            continue
        value = str(item.get("name") or item.get("model") or "").strip()
        if value:
            models.append(value)
    return models


async def _resolve_target_ollama_for_routing(
    routing: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any], list[str]]:
    target = str(routing.get("execution_backend", "local_ollama")).strip() or "local_ollama"
    updated = dict(routing)
    if target != "pixel_ollama":
        return OLLAMA_BASE_URL, updated, []

    pixel_hint = str(payload.get("pixel_ollama_url", "")).strip()
    shared_state = await asyncio.to_thread(read_shared_state)
    pixel_base = resolve_pixel_ollama_base_url(
        root_config=None,
        shared_state=shared_state,
    )
    if pixel_hint:
        pixel_base = pixel_hint
    if not pixel_base:
        updated["execution_backend"] = "local_ollama"
        updated["fallback_active"] = True
        updated["fallback_reason"] = "pixel_ollama_url_unresolved"
        return OLLAMA_BASE_URL, updated, []

    ok, reason, models = await probe_ollama_endpoint(pixel_base, timeout_s=DEFAULT_HTTP_TIMEOUT_S)
    if not ok:
        updated["execution_backend"] = "local_ollama"
        updated["fallback_active"] = True
        updated["fallback_reason"] = f"pixel_probe_failed:{reason}"
        return OLLAMA_BASE_URL, updated, []

    updated["pixel_ollama_url"] = pixel_base
    updated["pixel_probe"] = "ok"
    return pixel_base, updated, models


def _resolve_model(candidates: list[str], available_models: list[str]) -> str:
    normalized: list[str] = []
    seen: set[str] = set()
    for raw in candidates:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    if available_models:
        for candidate in normalized:
            if candidate in available_models:
                return candidate
        return available_models[0]
    if normalized:
        return normalized[0]
    return DEFAULT_MODEL


@app.post("/generate")
async def generate(payload: dict[str, Any]) -> dict[str, Any]:
    started = time.time()
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    brain_state["requests_total"] = int(brain_state.get("requests_total", 0) or 0) + 1

    task_type = str(payload.get("task_type", "chat")).strip() or "chat"
    routing = choose_backend(prompt, task_type, payload)
    target_ollama_base, routing, preloaded_models = await _resolve_target_ollama_for_routing(routing, payload)
    available_models = preloaded_models or await _list_ollama_models(target_ollama_base)
    model = _resolve_model(
        [
            str(payload.get("model", "")).strip(),
            str(routing.get("recommended_model", "")).strip(),
            DEFAULT_MODEL,
        ],
        available_models,
    )
    brain_state["last_routing"] = {
        "task_type": task_type,
        "preferred_backend": str(routing.get("preferred_backend", "local_ollama")),
        "execution_backend": str(routing.get("execution_backend", "local_ollama")),
        "route_hint": str(routing.get("route_hint", "brain_local")),
        "recommended_model": str(routing.get("recommended_model", "")),
        "selected_model": model,
        "ollama_target_url": target_ollama_base,
    }
    if MICRO_BRAIN_ENABLED and _micro_brain is not None:
        decision = _micro_brain.decide(
            prompt,
            {
                "workers": brain_state.get("workers", {}),
                "response_p95_ms": brain_state.get("response_p95_ms", 0.0),
            },
        )
        if not decision.wake_ollama and decision.quick_response:
            elapsed_ms = (time.time() - started) * 1000.0
            brain_state["last_generate_ms"] = round(elapsed_ms, 2)
            brain_state["micro_shortcuts"] = int(brain_state.get("micro_shortcuts", 0) or 0) + 1
            _update_latency_stats(elapsed_ms)
            return {
                "status": "micro",
                "model": "microgpt-lite",
                "response": decision.quick_response,
                "reason": decision.reason,
                "task_type": task_type,
                "routing": routing,
            }

    if str(routing.get("execution_backend", "local_ollama")).strip() != "pixel_ollama" and not brain_state["ollama_up"]:
        elapsed_ms = (time.time() - started) * 1000.0
        brain_state["last_generate_ms"] = round(elapsed_ms, 2)
        brain_state["stub_calls"] = int(brain_state.get("stub_calls", 0) or 0) + 1
        _update_latency_stats(elapsed_ms)
        return {
            "status": "stub",
            "model": "stub",
            "response": f"[stub] {prompt[:120]}",
            "task_type": task_type,
            "routing": routing,
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
            timeout=DEFAULT_HTTP_TIMEOUT_S,
            base_url=target_ollama_base,
        )
        res.raise_for_status()
        data = res.json()
    except Exception as exc:
        can_retry_local = (
            str(routing.get("execution_backend", "")).strip() == "pixel_ollama"
            and target_ollama_base.rstrip("/") != OLLAMA_BASE_URL.rstrip("/")
        )
        if can_retry_local:
            try:
                fallback_res = await _ollama_request(
                    "POST",
                    "/api/generate",
                    payload=req_payload,
                    timeout=DEFAULT_HTTP_TIMEOUT_S,
                    base_url=OLLAMA_BASE_URL,
                )
                fallback_res.raise_for_status()
                data = fallback_res.json()
                routing["execution_backend"] = "local_ollama"
                routing["fallback_active"] = True
                routing["fallback_reason"] = f"pixel_generate_failed:{_http_error_brief(exc)}"
                elapsed_ms = (time.time() - started) * 1000.0
                brain_state["last_generate_ms"] = round(elapsed_ms, 2)
                brain_state["ollama_calls"] = int(brain_state.get("ollama_calls", 0) or 0) + 1
                _update_latency_stats(elapsed_ms)
                return {
                    "status": "ok",
                    "model": model,
                    "response": str(data.get("response", "")).strip(),
                    "task_type": task_type,
                    "routing": routing,
                }
            except Exception:
                pass
        elapsed_ms = (time.time() - started) * 1000.0
        brain_state["last_generate_ms"] = round(elapsed_ms, 2)
        brain_state["stub_calls"] = int(brain_state.get("stub_calls", 0) or 0) + 1
        _update_latency_stats(elapsed_ms)
        return {
            "status": "stub",
            "model": "stub",
            "response": f"[stub-fallback] {prompt[:120]}",
            "error": _http_error_brief(exc),
            "task_type": task_type,
            "routing": routing,
        }
    elapsed_ms = (time.time() - started) * 1000.0
    brain_state["last_generate_ms"] = round(elapsed_ms, 2)
    brain_state["ollama_calls"] = int(brain_state.get("ollama_calls", 0) or 0) + 1
    _update_latency_stats(elapsed_ms)
    return {
        "status": "ok",
        "model": model,
        "response": str(data.get("response", "")).strip(),
        "task_type": task_type,
        "routing": routing,
    }


def main() -> int:
    if BRAIN_SOCKET_PATH:
        try:
            Path(BRAIN_SOCKET_PATH).unlink(missing_ok=True)
        except Exception:
            pass
        uvicorn.run(app, uds=BRAIN_SOCKET_PATH, log_level="info")
    else:
        uvicorn.run(app, host=BRAIN_HOST, port=BRAIN_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
