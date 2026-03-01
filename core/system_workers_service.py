"""Workers Edge helpers for health probing and diagram payloads."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Mapping


def _truncate_detail(detail: Any, limit: int = 160) -> str:
    text = str(detail or "").strip() or "online"
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


@dataclass(frozen=True)
class WorkerHealthDeps:
    integrations_snapshot: Callable[[], Awaitable[dict[str, Any]]]
    ipc_health: Callable[[str, str, float], Awaitable[Any]]
    timeout_s: float = 0.8


async def probe_worker_health(
    service: str,
    fallback_base: str,
    *,
    deps: WorkerHealthDeps,
) -> tuple[str, str]:
    if service == "api":
        return "ok", "loopback"
    if service == "picobot":
        integrations = await deps.integrations_snapshot()
        picobot = integrations.get("picobot", {}) if isinstance(integrations, dict) else {}
        status = str(picobot.get("status", "offline"))
        detail = str(picobot.get("detail", "picobot unavailable"))
        return status, detail
    try:
        response = await deps.ipc_health(service, fallback_base, float(deps.timeout_s))
        if not response.is_success:
            return "offline", f"http {response.status_code}"
        payload = response.json()
        status = str(payload.get("status", "ok")).lower()
        detail = payload.get("detail") or payload.get("service") or payload.get("name") or "online"
        return status, _truncate_detail(detail)
    except Exception as exc:
        return "offline", str(exc)


def build_worker_entry(worker_spec: Mapping[str, Any], *, status: str, detail: str) -> dict[str, Any]:
    return {
        "name": str(worker_spec["name"]),
        "label": str(worker_spec["label"]),
        "status": str(status),
        "meta": str(worker_spec["meta"]),
        "detail": str(detail),
        "worker_type": str(worker_spec.get("worker_type", "edge")),
        "ipc": str(worker_spec.get("ipc", "unix")),
    }


async def collect_edge_workers(
    worker_specs: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    *,
    deps: WorkerHealthDeps,
) -> list[dict[str, Any]]:
    health_results = await asyncio.gather(
        *[
            probe_worker_health(
                str(item["service"]),
                str(item["fallback_base"]),
                deps=deps,
            )
            for item in worker_specs
        ]
    )
    return [
        build_worker_entry(item, status=status, detail=detail)
        for item, (status, detail) in zip(worker_specs, health_results)
    ]


def build_docker_diagram_payload(
    *,
    containers: Any,
    workers: list[dict[str, Any]],
    links: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
    now: float,
) -> dict[str, Any]:
    return {
        "ts": float(now),
        "containers": containers,
        "workers": workers,
        "links": list(links),
    }
