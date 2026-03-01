import asyncio
import importlib
import logging
import os
from pathlib import Path
from types import ModuleType
from typing import List, Type

from core.config import DidierConfig
from core.config_loader import LoadedConfig
from core.config_loader import load_runtime_config
from core.config_schema import DidierRuntimeConfig
from tentacles.base import BaseTentacle


def _flag_enabled(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


class Orchestrator:
    def __init__(
        self,
        config_path: str = "config/config.json",
        tentacles_path: str = "tentacles",
    ) -> None:
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config_path = Path(config_path)
        self._config: DidierConfig
        self._loaded_config: LoadedConfig
        self._runtime_config: DidierRuntimeConfig
        self._tentacles_path = Path(tentacles_path)
        self._tentacles: List[BaseTentacle] = []
        self._tentacle_map: dict[str, BaseTentacle] = {}
        self._stop_event = asyncio.Event()
        self._startup_order = {
            "actuators": 10,
            "brain": 20,
            "music": 30,
            "vocal": 40,
            "vision": 50,
        }
        self.reload_config()

    @property
    def config(self) -> DidierConfig:
        return self._config

    @property
    def loaded_config(self) -> LoadedConfig:
        return self._loaded_config

    @property
    def runtime_config(self) -> DidierRuntimeConfig:
        return self._runtime_config

    @property
    def config_path(self) -> Path:
        return self._config_path

    @property
    def config_fingerprint(self) -> str:
        return self._loaded_config.fingerprint

    def reload_config(self, path: str | Path | None = None) -> None:
        loaded = load_runtime_config(path or self._config_path)
        self._config_path = loaded.path
        self._loaded_config = loaded
        self._runtime_config = loaded.runtime
        self._config = loaded.to_legacy()
        self._tentacle_start_timeout = float(
            self._config.get("system.tentacle_start_timeout_seconds", 12)
        )
        self._asr_worker_mode = _flag_enabled(
            self._config.get("asr.worker_mode", False)
        ) or _flag_enabled(os.getenv("DIDIER_ASR_WORKER_MODE", "0"))
        for warning in loaded.warnings:
            self._logger.warning("Config warning: %s", warning)

    def _discover_tentacle_modules(self) -> List[ModuleType]:
        if not self._tentacles_path.exists():
            self._logger.warning("Tentacles path not found: %s", self._tentacles_path)
            return []

        modules = []
        paths = sorted(
            self._tentacles_path.glob("*.py"),
            key=lambda p: (self._startup_order.get(p.stem, 100), p.stem),
        )
        for path in paths:
            if path.name.startswith("_") or path.name == "base.py":
                continue
            if self._asr_worker_mode and path.stem == "hearing":
                self._logger.info(
                    "Skipping tentacle %s (ASR worker mode enabled).", path.stem
                )
                continue
            module_name = f"tentacles.{path.stem}"
            try:
                modules.append(importlib.import_module(module_name))
            except Exception:
                self._logger.exception("Failed to import tentacle module %s", module_name)
        return modules

    def _load_tentacle_class(self, module: ModuleType) -> Type[BaseTentacle] | None:
        tentacle_cls = getattr(module, "Tentacle", None)
        if tentacle_cls is None:
            self._logger.warning("Module %s has no Tentacle class", module.__name__)
            return None
        if not issubclass(tentacle_cls, BaseTentacle):
            self._logger.warning(
                "Tentacle %s does not extend BaseTentacle", module.__name__
            )
            return None
        return tentacle_cls

    async def start(self) -> None:
        self._logger.info("Loading tentacles from %s", self._tentacles_path)
        for module in self._discover_tentacle_modules():
            tentacle_cls = self._load_tentacle_class(module)
            if not tentacle_cls:
                continue
            try:
                tentacle = await asyncio.to_thread(
                    tentacle_cls,
                    self._config,
                    orchestrator=self,
                )
            except Exception:
                self._logger.exception(
                    "Failed to instantiate tentacle %s", module.__name__
                )
                continue
            try:
                await asyncio.wait_for(
                    tentacle.start(), timeout=self._tentacle_start_timeout
                )
            except asyncio.TimeoutError:
                self._logger.error(
                    "Tentacle start timeout after %.1fs: %s",
                    self._tentacle_start_timeout,
                    tentacle.name,
                )
                try:
                    await tentacle.stop()
                except Exception:
                    self._logger.debug(
                        "Tentacle stop after timeout failed: %s",
                        tentacle.name,
                        exc_info=True,
                    )
                continue
            except Exception:
                self._logger.exception("Tentacle start failed: %s", tentacle.name)
                continue
            self._tentacles.append(tentacle)
            self._tentacle_map[tentacle.name] = tentacle
            self._logger.info("Tentacle loaded: %s", tentacle.name)

        if not self._tentacles:
            self._logger.warning("No tentacles loaded.")

    async def stop(self) -> None:
        if self._stop_event.is_set():
            return
        self._stop_event.set()
        await asyncio.gather(*(t.stop() for t in self._tentacles), return_exceptions=True)
        self._logger.info("All tentacles stopped.")

    async def run(self) -> None:
        self._logger.info("Didier orchestrator running.")
        await self._stop_event.wait()

    def get_tentacle(self, name: str) -> BaseTentacle | None:
        return self._tentacle_map.get(name)
