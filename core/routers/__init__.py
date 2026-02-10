"""Core package for Didier orchestrator."""
from .ai import router as ai_router
from .system import router as system_router
from .vision import router as vision_router

__all__ = ["system_router", "vision_router", "ai_router"]
