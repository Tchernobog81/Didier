"""Async Picobot HTTP adapter helpers."""

from __future__ import annotations

from typing import Any

import httpx

from core.ai_backend_policy import candidate_picobot_bases
from core.config_schema import PicobotConfig

DEFAULT_PICOBOT_BASES = ("http://127.0.0.1:3901",)


def _normalized_timeout(timeout_s: float) -> float:
    return max(0.1, float(timeout_s))


async def picobot_http_call(
    *,
    picobot_config: PicobotConfig,
    method: str,
    paths: tuple[str, ...],
    payload: dict[str, Any] | None,
    timeout_s: float,
    fallback_bases: tuple[str, ...] = DEFAULT_PICOBOT_BASES,
) -> dict[str, Any]:
    timeout = _normalized_timeout(timeout_s)
    method_up = str(method or "GET").upper()
    last_error = "picobot endpoint unavailable"
    bases = candidate_picobot_bases(
        picobot_config,
        fallback_bases=fallback_bases,
    )
    for base in bases:
        for path in paths:
            endpoint = f"{base}{path}"
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    if method_up == "GET":
                        response = await client.get(endpoint, params=payload or {})
                    else:
                        response = await client.request(method_up, endpoint, json=payload or {})
                if not response.is_success:
                    last_error = f"http {response.status_code} on {endpoint}"
                    continue
                try:
                    body: Any = response.json()
                except Exception:
                    body = {"response": str(response.text or "").strip()}
                if isinstance(body, dict):
                    data = dict(body)
                else:
                    data = {"response": str(body)}
                data.setdefault("ok", True)
                data.setdefault("source", "picobot")
                data.setdefault("endpoint", endpoint)
                return data
            except Exception as exc:
                last_error = f"{type(exc).__name__} on {endpoint}: {exc}"
    return {"ok": False, "error": last_error}


async def react_from_picobot(
    *,
    picobot_config: PicobotConfig,
    payload: dict[str, Any],
    timeout_s: float,
    fallback_bases: tuple[str, ...] = DEFAULT_PICOBOT_BASES,
) -> dict[str, Any]:
    return await picobot_http_call(
        picobot_config=picobot_config,
        method="POST",
        paths=("/agent/react",),
        payload=payload,
        timeout_s=timeout_s,
        fallback_bases=fallback_bases,
    )


async def metrics_from_picobot(
    *,
    picobot_config: PicobotConfig,
    timeout_s: float,
    fallback_bases: tuple[str, ...] = DEFAULT_PICOBOT_BASES,
) -> dict[str, Any]:
    return await picobot_http_call(
        picobot_config=picobot_config,
        method="GET",
        paths=("/agent/metrics", "/metrics", "/health"),
        payload={},
        timeout_s=timeout_s,
        fallback_bases=fallback_bases,
    )


async def tasks_from_picobot(
    *,
    picobot_config: PicobotConfig,
    timeout_s: float,
    fallback_bases: tuple[str, ...] = DEFAULT_PICOBOT_BASES,
) -> dict[str, Any]:
    return await picobot_http_call(
        picobot_config=picobot_config,
        method="GET",
        paths=("/agent/tasks", "/tasks"),
        payload={},
        timeout_s=timeout_s,
        fallback_bases=fallback_bases,
    )


async def route_from_picobot(
    *,
    picobot_config: PicobotConfig,
    prompt: str,
    task_type: str,
    payload: dict[str, Any] | None,
    timeout_s: float,
    fallback_bases: tuple[str, ...] = DEFAULT_PICOBOT_BASES,
) -> dict[str, Any]:
    request_payload: dict[str, Any] = {
        "prompt": str(prompt or ""),
        "task_type": str(task_type or "chat"),
    }
    if isinstance(payload, dict):
        request_payload["context"] = dict(payload)
    return await picobot_http_call(
        picobot_config=picobot_config,
        method="POST",
        paths=("/agent/route",),
        payload=request_payload,
        timeout_s=timeout_s,
        fallback_bases=fallback_bases,
    )


async def memory_from_picobot(
    *,
    picobot_config: PicobotConfig,
    include_content: bool,
    timeout_s: float,
    fallback_bases: tuple[str, ...] = DEFAULT_PICOBOT_BASES,
) -> dict[str, Any]:
    return await picobot_http_call(
        picobot_config=picobot_config,
        method="GET",
        paths=("/agent/memory", "/memory"),
        payload={"include_content": bool(include_content)},
        timeout_s=timeout_s,
        fallback_bases=fallback_bases,
    )


async def memory_write_picobot(
    *,
    picobot_config: PicobotConfig,
    path: str,
    content: str,
    append: bool,
    timeout_s: float,
    fallback_bases: tuple[str, ...] = DEFAULT_PICOBOT_BASES,
) -> dict[str, Any]:
    return await picobot_http_call(
        picobot_config=picobot_config,
        method="POST",
        paths=("/agent/memory", "/memory"),
        payload={"path": path, "content": content, "append": bool(append)},
        timeout_s=timeout_s,
        fallback_bases=fallback_bases,
    )
