"""System router bridge for compatibility."""

from fastapi import APIRouter

from core.routers.system import router as _core_system_router

router = APIRouter()
router.include_router(_core_system_router)
