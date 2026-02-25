"""AI router bridge for compatibility."""

from fastapi import APIRouter

from core.routers.ai import router as _core_ai_router

router = APIRouter()
router.include_router(_core_ai_router)
