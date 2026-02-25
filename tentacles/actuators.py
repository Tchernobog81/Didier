import json
import logging
import socket
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
        self._yeelight_port = int(self.config.get("actuators.yeelight_port", 55443))
        self._yeelight_timeout = float(
            self.config.get("actuators.yeelight_timeout_seconds", 1.5)
        )
        self._yeelight_retries = int(
            self.config.get("actuators.yeelight_retries", 3)
        )
        self._yeelight_retry_delay = float(
            self.config.get("actuators.yeelight_retry_delay_seconds", 0.12)
        )
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

    def _persist_devices(self) -> None:
        try:
            payload = {"devices": {}}
            for device_id, device in self._devices.items():
                payload["devices"][device_id] = {
                    "type": device.get("type", "unknown"),
                    "ip": device.get("ip", ""),
                    "name": device.get("name", ""),
                    "validated": bool(device.get("validated", False)),
                    "capabilities": self._normalize_list(device.get("capabilities", [])),
                    "tags": self._normalize_list(device.get("tags", [])),
                    "last_command": device.get("last_command", None),
                    "last_validation": device.get("last_validation", None),
                }
            self._registry_path.parent.mkdir(parents=True, exist_ok=True)
            self._registry_path.write_text(
                json.dumps(payload, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            self._logger.exception("Failed to persist %s", self._registry_path)

    def _yeelight_request(
        self, ip: str, method: str, params: list[Any] | None = None
    ) -> dict[str, Any]:
        if not ip:
            return {"ok": False, "error": "missing ip"}
        request_id = int(time.time() * 1000) % 1000000
        payload = {
            "id": request_id,
            "method": method,
            "params": params or [],
        }
        try:
            data = (json.dumps(payload, separators=(",", ":")) + "\r\n").encode(
                "utf-8"
            )
            with socket.create_connection(
                (ip, self._yeelight_port), timeout=self._yeelight_timeout
            ) as sock:
                sock.settimeout(self._yeelight_timeout)
                sock.sendall(data)
                buffer = b""
                parsed: list[dict[str, Any]] = []
                while True:
                    try:
                        chunk = sock.recv(4096)
                    except socket.timeout:
                        break
                    if not chunk:
                        break
                    buffer += chunk
                    while b"\n" in buffer:
                        raw_line, buffer = buffer.split(b"\n", 1)
                        line = raw_line.decode("utf-8", errors="ignore").strip()
                        if not line:
                            continue
                        try:
                            response = json.loads(line)
                        except Exception:
                            continue
                        if not isinstance(response, dict):
                            continue
                        parsed.append(response)
                        if str(response.get("id", "")) != str(request_id):
                            continue
                        if response.get("error"):
                            return {"ok": False, "error": str(response.get("error"))}
                        return {"ok": True, "result": response.get("result")}
            if not parsed:
                return {"ok": False, "error": "no response"}
            for response in reversed(parsed):
                if str(response.get("id", "")) == str(request_id):
                    if response.get("error"):
                        return {"ok": False, "error": str(response.get("error"))}
                    return {"ok": True, "result": response.get("result")}
            return {"ok": False, "error": "no matching response"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _yeelight_request_retry(
        self,
        ip: str,
        method: str,
        params: list[Any] | None = None,
        attempts: int | None = None,
    ) -> dict[str, Any]:
        attempts = max(1, int(attempts or self._yeelight_retries))
        last: dict[str, Any] = {"ok": False, "error": "no response"}
        for idx in range(attempts):
            res = self._yeelight_request(ip, method, params)
            if res.get("ok", False):
                return res
            last = res
            if idx >= attempts - 1:
                break
            err = str(res.get("error", "")).lower()
            transient = (
                err in {"no response", "no matching response"}
                or "timed out" in err
                or "reset" in err
                or "refused" in err
            )
            if not transient:
                break
            time.sleep(self._yeelight_retry_delay * (idx + 1))
        return last

    def _yeelight_get_status(self, ip: str) -> dict[str, Any]:
        props = ["power", "bright", "ct", "rgb", "hue", "sat", "color_mode"]
        res = self._yeelight_request_retry(ip, "get_prop", props, attempts=3)
        if not res.get("ok", False):
            return {
                "reachable": False,
                "state": {},
                "error": str(res.get("error", "unreachable")),
            }
        values = res.get("result", None)
        if not isinstance(values, list):
            values = []
        state: dict[str, Any] = {}
        for idx, key in enumerate(props):
            state[key] = values[idx] if idx < len(values) else None
        state["power_on"] = str(state.get("power", "")).lower() == "on"
        return {"reachable": True, "state": state, "error": None}

    def _yeelight_command(
        self, device: dict[str, Any], action: str, params: dict[str, Any]
    ) -> tuple[bool, str | None]:
        ip = str(device.get("ip", ""))
        action_norm = action.lower().strip()
        if action_norm == "on":
            res = self._yeelight_request_retry(
                ip, "set_power", ["on", "smooth", 300], attempts=3
            )
            if res.get("ok", False):
                return True, None
            error = str(res.get("error", "set_power on failed"))
            if error == "no response":
                probe = self._yeelight_get_status(ip)
                state = probe.get("state", {}) if isinstance(probe.get("state"), dict) else {}
                if bool(probe.get("reachable", False)) and str(state.get("power", "")).lower() == "on":
                    return True, None
            return False, error
        if action_norm == "off":
            res = self._yeelight_request_retry(
                ip, "set_power", ["off", "smooth", 300], attempts=3
            )
            if res.get("ok", False):
                return True, None
            error = str(res.get("error", "set_power off failed"))
            if error == "no response":
                probe = self._yeelight_get_status(ip)
                state = probe.get("state", {}) if isinstance(probe.get("state"), dict) else {}
                if bool(probe.get("reachable", False)) and str(state.get("power", "")).lower() == "off":
                    return True, None
            return False, error
        if action_norm == "toggle":
            res = self._yeelight_request_retry(ip, "toggle", [], attempts=3)
            return bool(res.get("ok", False)), (
                None if res.get("ok", False) else str(res.get("error", "toggle failed"))
            )
        if action_norm in {"bright", "brightness"}:
            try:
                level = int(params.get("value", params.get("brightness", 100)))
            except Exception:
                return False, "invalid brightness"
            level = max(1, min(level, 100))
            res = self._yeelight_request_retry(
                ip, "set_bright", [level, "smooth", 300], attempts=3
            )
            if res.get("ok", False):
                return True, None
            error = str(res.get("error", "set_bright failed"))
            if error == "no response":
                probe = self._yeelight_get_status(ip)
                state = probe.get("state", {}) if isinstance(probe.get("state"), dict) else {}
                bright = state.get("bright", None)
                if bool(probe.get("reachable", False)) and str(bright) == str(level):
                    return True, None
            return False, error
        if action_norm in {"color", "rgb"}:
            raw = params.get("value", params.get("color", params.get("hex", "#ffffff")))
            rgb_value: int | None = None
            if isinstance(raw, str):
                text = raw.strip().lower()
                if text.startswith("#"):
                    text = text[1:]
                if text.startswith("0x"):
                    text = text[2:]
                if len(text) == 6:
                    try:
                        rgb_value = int(text, 16)
                    except Exception:
                        rgb_value = None
                else:
                    try:
                        rgb_value = int(text)
                    except Exception:
                        rgb_value = None
            else:
                try:
                    rgb_value = int(raw)
                except Exception:
                    rgb_value = None
            if rgb_value is None:
                return False, "invalid color"
            rgb_value = max(0, min(rgb_value, 16777215))
            res = self._yeelight_request_retry(
                ip, "set_rgb", [rgb_value, "smooth", 300], attempts=3
            )
            if res.get("ok", False):
                return True, None
            error = str(res.get("error", "set_rgb failed"))
            if error == "no response":
                probe = self._yeelight_get_status(ip)
                state = probe.get("state", {}) if isinstance(probe.get("state"), dict) else {}
                current_rgb = state.get("rgb", None)
                if bool(probe.get("reachable", False)) and str(current_rgb) == str(rgb_value):
                    return True, None
            return False, error
        if action_norm == "validate":
            status = self._yeelight_get_status(ip)
            return bool(status.get("reachable", False)), (
                None if status.get("reachable", False) else str(status.get("error", "validation failed"))
            )
        raise ValueError(f"unsupported action for yeelight: {action}")

    async def run(self) -> None:
        await self.stop_event.wait()

    def list_devices(self) -> list[dict[str, Any]]:
        return [dict(self._devices[device_id]) for device_id in sorted(self._devices)]

    def get_status(self, device_id: str) -> dict[str, Any]:
        device = self._devices.get(device_id, None)
        if not device:
            raise KeyError(device_id)
        device_type = str(device.get("type", "unknown")).lower()
        reachable = False
        state: dict[str, Any] = {}
        error: str | None = None
        if device_type == "yeelight":
            status = self._yeelight_get_status(str(device.get("ip", "")))
            reachable = bool(status.get("reachable", False))
            state = status.get("state", {}) if isinstance(status.get("state"), dict) else {}
            error = str(status.get("error")) if status.get("error") else None
        return {
            "id": device_id,
            "type": device_type,
            "ip": device.get("ip", ""),
            "name": device.get("name", ""),
            "validated": bool(device.get("validated", False)),
            "reachable": reachable,
            "state": state,
            "error": error,
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
        action_norm = action.lower().strip()
        ok = True
        error: str | None = None
        device_type = str(device.get("type", "unknown")).lower()

        if device_type == "yeelight":
            ok, error = self._yeelight_command(device, action_norm, payload)
            if action_norm == "validate":
                maybe_name = str(payload.get("name", "")).strip() if payload else ""
                if maybe_name:
                    device["name"] = maybe_name
                device["validated"] = bool(ok)
                result = "ok" if ok else f"ko:{error or 'unreachable'}"
                device["last_validation"] = {"ts": ts, "result": result}
        elif action_norm == "validate":
            maybe_name = str(payload.get("name", "")).strip() if payload else ""
            if maybe_name:
                device["name"] = maybe_name
            device["validated"] = True
            device["last_validation"] = {"ts": ts, "result": "stub-ok"}
        self._persist_devices()
        status = self.get_status(device_id)
        return {
            "ok": ok,
            "id": device_id,
            "action": action_norm,
            "params": payload,
            "ts": ts,
            "error": error,
            "reachable": status.get("reachable", False),
            "state": status.get("state", {}),
            "last_command": dict(last_command),
            "last_validation": device.get("last_validation", None),
        }


Tentacle = ActuatorsTentacle
