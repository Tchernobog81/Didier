"""Async brain worker adapter helpers."""

from __future__ import annotations

from typing import Any

from shared.ipc import request as ipc_request


def _normalized_timeout(timeout_s: float) -> float:
    return max(0.1, float(timeout_s))


async def generate_from_brain(
    *,
    prompt: str,
    task_type: str = "react_task",
    timeout_s: float,
) -> dict[str, Any]:
    timeout = _normalized_timeout(timeout_s)
    request_payload = {
        "prompt": str(prompt or ""),
        "task_type": str(task_type or "react_task"),
    }
    try:
        response = await ipc_request(
            "POST",
            "/generate",
            service="brain",
            payload=request_payload,
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"brain relay exception: {exc}"}
    if not response.is_success:
        return {"ok": False, "error": f"brain relay http {response.status_code}"}
    try:
        payload = response.json()
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    text = str(payload.get("response", "")).strip()
    return {
        "ok": True,
        "source": "brain_worker",
        "endpoint": "unix://brain/generate",
        "response": text,
        "data": payload,
    }
