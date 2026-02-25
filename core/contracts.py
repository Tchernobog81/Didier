"""Generic runtime contracts for community extensions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(slots=True, frozen=True)
class CapabilityRequest:
    """Portable resource request payload used by extensions."""

    capability: str
    priority: str = "normal"
    metadata: Mapping[str, Any] | None = None


class PeripheralContract(ABC):
    """Base contract for hardware-aware peripherals."""

    peripheral_id: str = "unknown"
    peripheral_type: str = "generic"

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def health_snapshot(self) -> dict[str, Any]:
        raise NotImplementedError


class ActuatorContract(ABC):
    """Base contract for any actuator command sink."""

    actuator_id: str = "unknown"

    @abstractmethod
    async def execute(
        self,
        action: str,
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        raise NotImplementedError


class TentacleContract(ABC):
    """Base contract for long-running tentacle workers."""

    name: str = "base"

    @abstractmethod
    async def run(self) -> None:
        raise NotImplementedError
