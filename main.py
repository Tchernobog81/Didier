"""Entrypoint de compatibilité.

Le monolithe historique a été archivé dans `legacy/main.py`.
L'application active est exposée par `core.api`.
"""

from core.api import app

__all__ = ["app"]
