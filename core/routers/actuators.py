from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/actuators", tags=["actuators"])


def _get_actuators_tentacle() -> Any:
    from core import api as api_module

    orchestrator = api_module._require_orchestrator()
    tentacle = orchestrator.get_tentacle("actuators")
    if not tentacle:
        raise HTTPException(status_code=503, detail="actuators tentacle not loaded")
    return tentacle


@router.get("")
async def list_actuators() -> dict[str, list[dict[str, Any]]]:
    tentacle = _get_actuators_tentacle()
    return {"devices": tentacle.list_devices()}


@router.get("/{id}/status")
async def actuator_status(id: str) -> dict[str, Any]:
    tentacle = _get_actuators_tentacle()
    try:
        return tentacle.get_status(id)
    except KeyError:
        raise HTTPException(status_code=404, detail="device not found")


@router.post("/{id}/command")
async def actuator_command(
    id: str, payload: dict[str, Any] | None = None
) -> dict[str, Any]:
    tentacle = _get_actuators_tentacle()
    action = str((payload or {}).get("action", "")).strip()
    if not action:
        raise HTTPException(status_code=400, detail="action required")
    params = (payload or {}).get("params", None)
    if params is not None and not isinstance(params, dict):
        params = {}
    try:
        return tentacle.command(id, action, params)
    except KeyError:
        raise HTTPException(status_code=404, detail="device not found")
