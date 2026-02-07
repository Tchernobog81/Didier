import asyncio
import logging
from abc import ABC, abstractmethod

from core.config import DidierConfig


class BaseTentacle(ABC):
    name = "base"

    def __init__(self, config: DidierConfig, orchestrator: object) -> None:
        self._config = config
        self._orchestrator = orchestrator
        self._logger = logging.getLogger(self.__class__.__name__)
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task | None = None

    @property
    def config(self) -> DidierConfig:
        return self._config

    @property
    def stop_event(self) -> asyncio.Event:
        return self._stop_event

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self.run())

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task:
            await asyncio.gather(self._task, return_exceptions=True)

    @abstractmethod
    async def run(self) -> None:
        raise NotImplementedError
