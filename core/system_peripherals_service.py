"""Peripheral inventory and toggle orchestration for system routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Mapping


def wifi_link_state(operstate_path: Path = Path("/sys/class/net/wlan0/operstate")) -> str:
    if operstate_path.exists():
        try:
            return operstate_path.read_text(encoding="utf-8").strip().lower() or "unknown"
        except Exception:
            return "unknown"
    return "not-present"


@dataclass(frozen=True)
class PeripheralServiceError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


@dataclass(frozen=True)
class SystemPeripheralsDeps:
    now: Callable[[], float]
    service_state: Callable[[str], Awaitable[tuple[bool, str]]]
    run_systemctl: Callable[[str, str], Awaitable[tuple[int, str]]]
    wifi_link_state: Callable[[], str] = wifi_link_state


async def build_peripheral_item(
    key: str,
    spec: Mapping[str, str],
    *,
    deps: SystemPeripheralsDeps,
) -> dict[str, Any]:
    service = str(spec["service"])
    active, state = await deps.service_state(service)
    item: dict[str, Any] = {
        "id": str(key),
        "label": str(spec["label"]),
        "kind": str(spec["kind"]),
        "channel": str(spec["channel"]),
        "service": service,
        "active": bool(active),
        "state": str(state),
    }
    if str(key) == "wifi":
        item["link_state"] = str(deps.wifi_link_state())
    return item


async def collect_peripherals(
    specs: Mapping[str, Mapping[str, str]],
    *,
    deps: SystemPeripheralsDeps,
) -> dict[str, Any]:
    items = await asyncio.gather(
        *[build_peripheral_item(key, spec, deps=deps) for key, spec in specs.items()]
    )
    return {
        "ok": True,
        "ts": float(deps.now()),
        "items": items,
    }


def _requested_enabled(body: dict[str, Any], *, current_active: bool) -> bool:
    if "enabled" in body:
        return bool(body.get("enabled"))
    action = str(body.get("action", "")).strip().lower()
    if action in {"start", "on", "enable"}:
        return True
    if action in {"stop", "off", "disable"}:
        return False
    return not bool(current_active)


async def toggle_peripheral(
    payload: dict[str, Any] | None,
    specs: Mapping[str, Mapping[str, str]],
    *,
    deps: SystemPeripheralsDeps,
) -> dict[str, Any]:
    body = payload or {}
    peripheral_id = str(body.get("id", "")).strip().lower()
    if peripheral_id not in specs:
        raise PeripheralServiceError(status_code=400, detail="unknown peripheral id")

    spec = specs[peripheral_id]
    service = str(spec["service"])
    current_active, current_state = await deps.service_state(service)
    requested_enabled = _requested_enabled(body, current_active=bool(current_active))
    cmd = "start" if requested_enabled else "stop"
    rc, detail = await deps.run_systemctl(cmd, service)
    if rc != 0:
        failure_detail = detail or f"rc={rc}"
        raise PeripheralServiceError(
            status_code=500,
            detail=f"systemctl {cmd} failed for {service}: {failure_detail}",
        )

    active, state = await deps.service_state(service)
    item = await build_peripheral_item(peripheral_id, spec, deps=deps)
    return {
        "ok": True,
        "ts": float(deps.now()),
        "id": peripheral_id,
        "service": service,
        "requested": cmd,
        "before": {"active": bool(current_active), "state": str(current_state)},
        "after": {"active": bool(active), "state": str(state)},
        "detail": detail,
        "item": item,
    }
