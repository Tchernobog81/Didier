"""Vision router unifié pour la phase de stabilisation.

Ce module expose un routeur unique et garde une compatibilité minimale
avec l'ancien endpoint `/see`.
"""

from typing import Any

from fastapi import APIRouter

from core.routers.vision import capture as _capture
from core.routers.vision import router as _core_vision_router

router = APIRouter()
router.include_router(_core_vision_router)


@router.get("/see")
async def see_legacy() -> dict[str, Any]:
    payload = await _capture()
    return {"status": "ok", "path": payload.get("path")}
