import json
import logging
import time
from pathlib import Path
from typing import Any

from tentacles.base import BaseTentacle


class ActuatorsTentacle(BaseTentacle):
    name = "actuators"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(f"Tentacle.{self.name}")
        self._devices: dict[str, dict[str, Any]] = {}
        self._registry_path = Path("config/actuators.json")
        self._load_devices()

    def _normalize_list(self, value: Any) -> list[Any]:
        if isinstance(value, list):
            return value
        if value is None:
            return []
        if isinstance(value, tuple):
            return list(value)
        return [value]

    def _normalize_devices(self, raw_devices: Any) -> dict[str, dict[str, Any]]:
        devices: dict[str, dict[str, Any]] = {}
        if not isinstance(raw_devices, dict):
            return devices
        for raw_id, raw_device in raw_devices.items():
            if not isinstance(raw_device, dict):
                continue
            device_id = str(raw_id)
            capabilities = [str(v) for v in self._normalize_list(raw_device.get("capabilities", []))]
            tags = [str(v) for v in self._normalize_list(raw_device.get("tags", []))]
            name = str(raw_device.get("name", "") or "")
            validated = bool(raw_device.get("validated", False))
            last_command = raw_device.get("last_command", None)
            if not isinstance(last_command, dict):
                last_command = None
            last_validation = raw_device.get("last_validation", None)
            if not isinstance(last_validation, dict):
                last_validation = None
            devices[device_id] = {
                "id": device_id,
                "type": str(raw_device.get("type", "unknown")),
                "name": name,
                "ip": str(raw_device.get("ip", "")),
                "validated": validated,
                "capabilities": capabilities,
                "tags": tags,
                "last_command": last_command,
                "last_validation": last_validation,
            }
        return devices

    def _load_devices(self) -> None:
        devices: dict[str, dict[str, Any]] = {}
        if self._registry_path.exists():
            try:
                payload = json.loads(self._registry_path.read_text(encoding="utf-8"))
                devices = self._normalize_devices(payload.get("devices", {}))
            except Exception:
                self._logger.exception("Failed to load %s", self._registry_path)
                devices = {}
        if not devices:
            devices = self._normalize_devices(self.config.get("actuators", {}))
        self._devices = devices

    async def run(self) -> None:
        await self.stop_event.wait()

    def list_devices(self) -> list[dict[str, Any]]:
        return [dict(self._devices[device_id]) for device_id in sorted(self._devices)]

    def get_status(self, device_id: str) -> dict[str, Any]:
        device = self._devices.get(device_id, None)
        if not device:
            raise KeyError(device_id)
        return {
            "id": device_id,
            "type": device.get("type", "unknown"),
            "ip": device.get("ip", ""),
            "name": device.get("name", ""),
            "validated": bool(device.get("validated", False)),
            "reachable": False,
            "state": {},
            "last_command": device.get("last_command", None),
            "last_validation": device.get("last_validation", None),
        }

    def command(
        self, device_id: str, action: str, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        device = self._devices.get(device_id, None)
        if not device:
            raise KeyError(device_id)
        action = str(action).strip()
        if not action:
            raise ValueError("action required")
        payload = params if isinstance(params, dict) else {}
        ts = time.time()
        last_command = {"ts": ts, "action": action, "params": payload}
        device["last_command"] = last_command
        if action == "validate":
            maybe_name = str(payload.get("name", "")).strip() if payload else ""
            if maybe_name:
                device["name"] = maybe_name
            device["validated"] = True
            device["last_validation"] = {"ts": ts, "result": "stub-ok"}
        return {
            "ok": True,
            "id": device_id,
            "action": action,
            "params": payload,
            "ts": ts,
            "last_command": dict(last_command),
            "last_validation": device.get("last_validation", None),
        }


Tentacle = ActuatorsTentacle
