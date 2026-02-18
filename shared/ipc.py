"""Internal IPC helpers (Unix sockets first, HTTP fallback)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx

_DEFAULT_SOCKET_BY_SERVICE = {
    "api": "/tmp/didier_api.sock",
    "vision": "/tmp/didier_vision.sock",
    "brain": "/tmp/didier_brain.sock",
    "audio": "/tmp/didier_audio.sock",
    "asr": "/tmp/didier_asr.sock",
}

_DEFAULT_BASE_BY_SERVICE = {
    "api": "http://127.0.0.1:5010",
    "vision": "http://127.0.0.1:5011",
    "brain": "http://127.0.0.1:5012",
    "audio": "http://127.0.0.1:5013",
    "asr": "http://127.0.0.1:5014",
}

_SOCKET_ENV_BY_SERVICE = {
    "api": "DIDIER_API_SOCK",
    "vision": "DIDIER_VISION_SOCK",
    "brain": "DIDIER_BRAIN_SOCK",
    "audio": "DIDIER_AUDIO_SOCK",
    "asr": "DIDIER_ASR_SOCK",
}

_BASE_ENV_BY_SERVICE = {
    "api": "DIDIER_API_URL",
    "vision": "DIDIER_VISION_URL",
    "brain": "DIDIER_BRAIN_URL",
    "audio": "DIDIER_AUDIO_URL",
    "asr": "DIDIER_ASR_URL",
}


def worker_socket(service: str) -> str:
    key = str(service).strip().lower()
    env_name = _SOCKET_ENV_BY_SERVICE.get(key)
    default = _DEFAULT_SOCKET_BY_SERVICE.get(key, "")
    if not env_name:
        return default
    return os.getenv(env_name, default).strip()


def worker_base_url(service: str) -> str:
    key = str(service).strip().lower()
    env_name = _BASE_ENV_BY_SERVICE.get(key)
    default = _DEFAULT_BASE_BY_SERVICE.get(key, "")
    if not env_name:
        return default
    return os.getenv(env_name, default).strip()


async def request(
    method: str,
    path: str,
    *,
    service: str | None = None,
    socket_path: str | None = None,
    base_url: str | None = None,
    payload: dict[str, Any] | None = None,
    timeout: float = 1.5,
) -> httpx.Response:
    """Execute an internal request with Unix socket priority and HTTP fallback."""

    normalized_service = str(service or "").strip().lower() or None
    resolved_socket = (socket_path or "").strip()
    if not resolved_socket and normalized_service:
        resolved_socket = worker_socket(normalized_service)
    resolved_base = (base_url or "").strip()
    if not resolved_base and normalized_service:
        resolved_base = worker_base_url(normalized_service)

    errors: list[str] = []
    if resolved_socket and Path(resolved_socket).exists():
        try:
            transport = httpx.AsyncHTTPTransport(uds=resolved_socket)
            async with httpx.AsyncClient(
                base_url="http://localhost",
                transport=transport,
                timeout=timeout,
            ) as client:
                return await client.request(method, path, json=payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"uds:{resolved_socket}: {exc}")

    if resolved_base:
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                return await client.request(method, f"{resolved_base}{path}", json=payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"http:{resolved_base}: {exc}")

    detail = "; ".join(errors) if errors else "no_ipc_target"
    raise RuntimeError(detail)


async def health(
    service: str,
    *,
    base_url: str | None = None,
    timeout: float = 1.0,
) -> dict[str, Any]:
    """Return normalized worker health payload."""

    try:
        response = await request(
            "GET",
            "/health",
            service=service,
            base_url=base_url,
            timeout=timeout,
        )
        if not response.is_success:
            return {"ok": False, "status": "offline", "detail": f"http {response.status_code}"}
        payload = response.json()
        status = str(payload.get("status", "ok")).lower()
        detail = payload.get("detail") or payload.get("service") or payload.get("name") or status
        return {"ok": status == "ok", "status": status, "detail": str(detail)}
    except Exception as exc:  # pragma: no cover
        return {"ok": False, "status": "offline", "detail": str(exc)}
