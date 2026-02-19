"""Unix-socket IPC client for OpenClaw native bridge."""

from __future__ import annotations

from typing import Any

from shared import ipc


async def relay_react(
    prompt: str,
    *,
    agent_id: str | None = None,
    session_key: str | None = None,
    wake_mode: str = "now",
    timeout_s: float = 3.0,
) -> dict[str, Any]:
    text = str(prompt or "").strip()
    if not text:
        return {"ok": False, "error": "prompt required"}

    payload: dict[str, Any] = {
        "prompt": text,
        "wake_mode": wake_mode if wake_mode == "next-heartbeat" else "now",
    }
    if agent_id:
        payload["agent_id"] = str(agent_id).strip()
    if session_key:
        payload["session_key"] = str(session_key).strip()

    timeout = max(0.5, min(float(timeout_s), 12.0))
    try:
        response = await ipc.request(
            "POST",
            "/react",
            service="openclaw",
            payload=payload,
            timeout=timeout + 1.0,
        )
    except Exception as exc:
        return {"ok": False, "error": f"openclaw ipc unavailable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {"ok": False, "error": "invalid_openclaw_ipc_response"}
    if "ok" not in data:
        data["ok"] = response.is_success
    if not response.is_success and "error" not in data:
        data["error"] = f"openclaw ipc http {response.status_code}"
    return data


async def fetch_metrics(timeout_s: float = 4.0) -> dict[str, Any]:
    timeout = max(0.5, min(float(timeout_s), 12.0))
    # Bridge /metrics delegates to OpenClaw health probing; keep margin above inner timeout.
    ipc_timeout = min(20.0, timeout + 4.0)
    try:
        response = await ipc.request(
            "GET",
            f"/metrics?timeout_s={timeout}",
            service="openclaw",
            timeout=ipc_timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"openclaw ipc unavailable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {"ok": False, "error": "invalid_openclaw_metrics_response"}
    if "ok" not in data:
        data["ok"] = response.is_success
    if not response.is_success and "error" not in data:
        data["error"] = f"openclaw ipc http {response.status_code}"
    return data


async def fetch_memory(include_content: bool = False, timeout_s: float = 3.0) -> dict[str, Any]:
    timeout = max(0.5, min(float(timeout_s), 12.0))
    path = "/memory?include_content=1" if include_content else "/memory"
    try:
        response = await ipc.request(
            "GET",
            path,
            service="openclaw",
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"openclaw ipc unavailable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {"ok": False, "error": "invalid_openclaw_memory_response"}
    if "ok" not in data:
        data["ok"] = response.is_success
    if not response.is_success and "error" not in data:
        data["error"] = f"openclaw ipc http {response.status_code}"
    return data


async def fetch_tasks(timeout_s: float = 3.0) -> dict[str, Any]:
    timeout = max(0.5, min(float(timeout_s), 12.0))
    try:
        response = await ipc.request(
            "GET",
            "/tasks",
            service="openclaw",
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"openclaw ipc unavailable: {exc}", "tasks": []}

    try:
        data = response.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {"ok": False, "error": "invalid_openclaw_tasks_response", "tasks": []}
    if "tasks" not in data or not isinstance(data.get("tasks"), list):
        data["tasks"] = []
    if "ok" not in data:
        data["ok"] = response.is_success
    if not response.is_success and "error" not in data:
        data["error"] = f"openclaw ipc http {response.status_code}"
    return data


async def write_memory(
    path: str,
    content: str,
    *,
    append: bool = False,
    timeout_s: float = 3.0,
) -> dict[str, Any]:
    target = str(path or "").strip()
    if not target:
        return {"ok": False, "error": "path required"}
    timeout = max(0.5, min(float(timeout_s), 12.0))
    payload = {
        "path": target,
        "content": str(content or ""),
        "append": bool(append),
    }
    try:
        response = await ipc.request(
            "POST",
            "/memory",
            service="openclaw",
            payload=payload,
            timeout=timeout,
        )
    except Exception as exc:
        return {"ok": False, "error": f"openclaw ipc unavailable: {exc}"}

    try:
        data = response.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {"ok": False, "error": "invalid_openclaw_memory_write_response"}
    if "ok" not in data:
        data["ok"] = response.is_success
    if not response.is_success and "error" not in data:
        data["error"] = f"openclaw ipc http {response.status_code}"
    return data
