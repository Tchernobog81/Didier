import concurrent.futures
import json
import itertools
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
        self._yeelight_discovery_timeout = float(
            self.config.get("actuators.yeelight_discovery_timeout_seconds", 0.8)
        )
        self._yeelight_discovery_rounds = int(
            self.config.get("actuators.yeelight_discovery_rounds", 2)
        )
        self._yeelight_scan_timeout = float(
            self.config.get("actuators.yeelight_scan_timeout_seconds", 0.6)
        )
        self._yeelight_scan_radius = int(
            self.config.get("actuators.yeelight_scan_radius", 4)
        )
        self._yeelight_scan_workers = int(
            self.config.get("actuators.yeelight_scan_workers", 12)
        )
        self._yeelight_scan_attempts = int(
            self.config.get("actuators.yeelight_scan_attempts", 2)
        )
        self._yeelight_scan_rounds = int(
            self.config.get("actuators.yeelight_scan_rounds", 2)
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

    def _normalize_optional_token(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.lower() in {"none", "null"}:
            return None
        return text

    def _yeelight_identity_for_ip(self, ip: str) -> str | None:
        ip = str(ip or "").strip()
        if not ip:
            return None
        arp_path = getattr(self, "_arp_path", Path("/proc/net/arp"))
        try:
            text = Path(arp_path).read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None
        for raw_line in text.splitlines()[1:]:
            parts = raw_line.split()
            if len(parts) < 4:
                continue
            if parts[0] != ip:
                continue
            mac = self._normalize_optional_token(parts[3])
            if not mac or mac.lower() == "00:00:00:00:00:00":
                return None
            return f"mac:{mac.lower()}"
        return None

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
            yeelight_id = self._normalize_optional_token(raw_device.get("yeelight_id", None))
            devices[device_id] = {
                "id": device_id,
                "type": str(raw_device.get("type", "unknown")),
                "name": name,
                "ip": str(raw_device.get("ip", "")),
                "yeelight_id": yeelight_id,
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
            payload: dict[str, Any] = {}
            if self._registry_path.exists():
                try:
                    existing = json.loads(self._registry_path.read_text(encoding="utf-8"))
                    if isinstance(existing, dict):
                        payload.update(existing)
                except Exception:
                    self._logger.debug(
                        "Failed to preserve existing actuator registry extras",
                        exc_info=True,
                    )
            payload["devices"] = {}
            for device_id, device in self._devices.items():
                payload["devices"][device_id] = {
                    "type": device.get("type", "unknown"),
                    "ip": device.get("ip", ""),
                    "name": device.get("name", ""),
                    "yeelight_id": device.get("yeelight_id", None),
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

    def _is_yeelight_transport_error(self, error: str | None) -> bool:
        if not error:
            return False
        text = str(error).lower()
        return (
            text in {"no response", "no matching response"}
            or "timed out" in text
            or "reset" in text
            or "refused" in text
        )

    def _yeelight_discover(self) -> list[dict[str, Any]]:
        request = (
            "M-SEARCH * HTTP/1.1\r\n"
            "HOST: 239.255.255.250:1982\r\n"
            'MAN: "ssdp:discover"\r\n'
            "ST: wifi_bulb\r\n"
        ).encode("ascii")
        discovered: dict[str, dict[str, Any]] = {}
        rounds = max(1, self._yeelight_discovery_rounds)
        timeout = max(0.1, self._yeelight_discovery_timeout)
        for _ in range(rounds):
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            try:
                sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
                sock.settimeout(timeout)
                sock.sendto(request, ("239.255.255.250", 1982))
                while True:
                    try:
                        data, addr = sock.recvfrom(8192)
                    except socket.timeout:
                        break
                    text = data.decode("utf-8", errors="ignore")
                    entry: dict[str, Any] = {"ip": addr[0]}
                    for raw_line in text.splitlines():
                        line = raw_line.strip()
                        if not line or ":" not in line:
                            continue
                        key, value = line.split(":", 1)
                        entry[key.strip().lower()] = value.strip()
                    bulb_id = (
                        self._normalize_optional_token(entry.get("id", None))
                        or self._yeelight_identity_for_ip(addr[0])
                        or self._normalize_optional_token(entry.get("location", None))
                        or addr[0]
                    )
                    entry["id"] = bulb_id
                    state = {
                        "power": entry.get("power", None),
                        "bright": entry.get("bright", None),
                        "ct": entry.get("ct", None),
                        "rgb": entry.get("rgb", None),
                        "hue": entry.get("hue", None),
                        "sat": entry.get("sat", None),
                        "color_mode": entry.get("color_mode", None),
                    }
                    state["power_on"] = str(state.get("power", "")).lower() == "on"
                    entry["state"] = state
                    discovered[bulb_id] = entry
            except Exception:
                self._logger.debug("Yeelight discovery round failed", exc_info=True)
            finally:
                sock.close()
        expected = len(
            [
                device
                for device in self._devices.values()
                if str(device.get("type", "unknown")).lower() == "yeelight"
            ]
        )
        if len(discovered) < expected:
            rounds = max(1, self._yeelight_scan_rounds)
            for _ in range(rounds):
                for entry in self._yeelight_scan_nearby_ips():
                    ip = str(entry.get("ip", "")).strip()
                    if not ip:
                        continue
                    merged_key: str | None = None
                    for bulb_id, bulb in discovered.items():
                        if str(bulb.get("ip", "")).strip() == ip:
                            merged_key = bulb_id
                            break
                    if merged_key is None:
                        discovered[f"scan:{ip}"] = entry
                        continue
                    merged = discovered[merged_key]
                    if not merged.get("state") and entry.get("state"):
                        merged["state"] = entry["state"]
                if len(discovered) >= expected:
                    break
        return list(discovered.values())

    def _yeelight_probe_ip_once(self, ip: str) -> dict[str, Any] | None:
        if not ip:
            return None
        props = ["power", "bright", "ct", "rgb", "hue", "sat", "color_mode"]
        request_id = 1
        payload = {
            "id": request_id,
            "method": "get_prop",
            "params": props,
        }
        timeout = max(0.1, self._yeelight_scan_timeout)
        attempts = max(1, self._yeelight_scan_attempts)
        data = (json.dumps(payload, separators=(",", ":")) + "\r\n").encode("utf-8")
        for _ in range(attempts):
            try:
                with socket.create_connection((ip, self._yeelight_port), timeout=timeout) as sock:
                    sock.settimeout(timeout)
                    sock.sendall(data)
                    buffer = b""
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
                            if str(response.get("id", "")) != str(request_id):
                                continue
                            if not isinstance(response.get("result", None), list):
                                return None
                            values = response["result"]
                            state: dict[str, Any] = {}
                            for idx, key in enumerate(props):
                                state[key] = values[idx] if idx < len(values) else None
                            state["power_on"] = str(state.get("power", "")).lower() == "on"
                            return {
                                "ip": ip,
                                "id": self._yeelight_identity_for_ip(ip),
                                "state": state,
                            }
            except Exception:
                continue
        return None

    def _yeelight_scan_nearby_ips(self) -> list[dict[str, Any]]:
        yeelight_devices = [
            device
            for device in self._devices.values()
            if str(device.get("type", "unknown")).lower() == "yeelight"
        ]
        if not yeelight_devices:
            return []
        candidates: set[str] = set()
        radius = max(0, self._yeelight_scan_radius)
        for device in yeelight_devices:
            ip = str(device.get("ip", "")).strip()
            if not ip:
                continue
            parts = ip.split(".")
            if len(parts) != 4:
                continue
            try:
                last = int(parts[-1])
            except Exception:
                continue
            prefix = ".".join(parts[:3])
            for offset in range(-radius, radius + 1):
                candidate = last + offset
                if candidate < 1 or candidate > 254:
                    continue
                candidates.add(f"{prefix}.{candidate}")
        if not candidates:
            return []
        ordered = sorted(candidates, key=lambda item: [int(part) for part in item.split(".")])
        results: list[dict[str, Any]] = []
        workers = max(1, min(self._yeelight_scan_workers, len(ordered)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            for entry in executor.map(self._yeelight_probe_ip_once, ordered):
                if entry:
                    results.append(entry)
        return results

    def _ip_distance(self, left: str, right: str) -> int:
        try:
            left_last = int(str(left).strip().split(".")[-1])
            right_last = int(str(right).strip().split(".")[-1])
            return abs(left_last - right_last)
        except Exception:
            return 9999

    def _device_seed_ip(self, device: dict[str, Any]) -> str:
        raw_id = str(device.get("id", "")).strip()
        if raw_id.startswith("yl_"):
            candidate = raw_id[3:].replace("_", ".")
            parts = candidate.split(".")
            if len(parts) == 4:
                try:
                    octets = [int(part) for part in parts]
                except Exception:
                    octets = []
                if len(octets) == 4 and all(0 <= part <= 255 for part in octets):
                    return candidate
        return str(device.get("ip", "")).strip()

    def _pair_unresolved_yeelight_devices(
        self,
        devices: list[dict[str, Any]],
        bulbs: list[dict[str, Any]],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        if not devices or not bulbs or len(devices) != len(bulbs):
            return []
        if len(devices) > 7:
            ordered_devices = sorted(devices, key=lambda item: str(item.get("id", "")))
            ordered_bulbs = sorted(bulbs, key=lambda item: str(item.get("ip", "")))
            return list(zip(ordered_devices, ordered_bulbs))
        best_cost: int | None = None
        best_pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for perm in itertools.permutations(bulbs, len(devices)):
            cost = 0
            pairs: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for device, bulb in zip(devices, perm):
                pairs.append((device, bulb))
                cost += self._ip_distance(
                    self._device_seed_ip(device),
                    bulb.get("ip", ""),
                )
            if best_cost is None or cost < best_cost:
                best_cost = cost
                best_pairs = pairs
        return best_pairs

    def _reconcile_yeelight_devices(
        self, discovered: list[dict[str, Any]] | None = None
    ) -> dict[str, dict[str, Any]]:
        yeelight_devices = [
            device
            for device in self._devices.values()
            if str(device.get("type", "unknown")).lower() == "yeelight"
        ]
        if not yeelight_devices:
            return {}
        bulbs = discovered if discovered is not None else self._yeelight_discover()
        if not bulbs:
            return {}
        bulbs_by_id: dict[str, dict[str, Any]] = {}
        for bulb in bulbs:
            bulb_id = self._normalize_optional_token(bulb.get("id", None))
            if bulb_id:
                bulbs_by_id[bulb_id] = bulb
        bulbs_by_ip = {
            str(bulb.get("ip", "")).strip(): bulb
            for bulb in bulbs
            if str(bulb.get("ip", "")).strip()
        }
        matched: dict[str, dict[str, Any]] = {}
        used_bulb_ids: set[str] = set()
        used_bulb_ips: set[str] = set()
        changed = False

        for device in yeelight_devices:
            bulb_id = self._normalize_optional_token(device.get("yeelight_id", None))
            bulb = bulbs_by_id.get(bulb_id, None) if bulb_id else None
            if bulb is None:
                continue
            bulb_ip = str(bulb.get("ip", "")).strip()
            if bulb_ip in used_bulb_ips:
                continue
            matched[str(device["id"])] = bulb
            matched_bulb_id = self._normalize_optional_token(bulb.get("id", None))
            if matched_bulb_id:
                used_bulb_ids.add(matched_bulb_id)
            if bulb_ip:
                used_bulb_ips.add(bulb_ip)
            next_ip = bulb_ip
            if next_ip and next_ip != str(device.get("ip", "")).strip():
                device["ip"] = next_ip
                changed = True

        pass2_devices = sorted(
            yeelight_devices,
            key=lambda item: (
                0
                if str(item.get("ip", "")).strip() == self._device_seed_ip(item)
                else 1,
                self._ip_distance(
                    self._device_seed_ip(item),
                    str(item.get("ip", "")).strip(),
                ),
                str(item.get("id", "")),
            ),
        )
        for device in pass2_devices:
            device_id = str(device["id"])
            if device_id in matched:
                continue
            bulb = bulbs_by_ip.get(str(device.get("ip", "")).strip(), None)
            if bulb is None:
                continue
            bulb_ip = str(bulb.get("ip", "")).strip()
            if bulb_ip in used_bulb_ips:
                continue
            matched[device_id] = bulb
            matched_bulb_id = self._normalize_optional_token(bulb.get("id", None))
            if matched_bulb_id:
                used_bulb_ids.add(matched_bulb_id)
            if bulb_ip:
                used_bulb_ips.add(bulb_ip)
            bulb_id = self._normalize_optional_token(bulb.get("id", None))
            if bulb_id and bulb_id != device.get("yeelight_id", None):
                device["yeelight_id"] = bulb_id
                changed = True

        unresolved_devices = [
            device for device in yeelight_devices if str(device["id"]) not in matched
        ]
        unused_bulbs = [
            bulb
            for bulb in bulbs
            if str(bulb.get("ip", "")).strip() not in used_bulb_ips
            and (
                not self._normalize_optional_token(bulb.get("id", None))
                or self._normalize_optional_token(bulb.get("id", None)) not in used_bulb_ids
            )
        ]
        if (
            len(bulbs) >= len(yeelight_devices)
            and unresolved_devices
            and unused_bulbs
            and len(unresolved_devices) == len(unused_bulbs)
        ):
            pairs = self._pair_unresolved_yeelight_devices(unresolved_devices, unused_bulbs)
            for device, bulb in pairs:
                device_id = str(device["id"])
                matched[device_id] = bulb
                bulb_ip = str(bulb.get("ip", "")).strip()
                bulb_id = self._normalize_optional_token(bulb.get("id", None))
                if bulb_ip:
                    used_bulb_ips.add(bulb_ip)
                if bulb_id:
                    used_bulb_ids.add(bulb_id)
                next_ip = str(bulb.get("ip", "")).strip()
                next_bulb_id = bulb_id or None
                if next_ip and next_ip != str(device.get("ip", "")).strip():
                    device["ip"] = next_ip
                    changed = True
                if next_bulb_id and next_bulb_id != device.get("yeelight_id", None):
                    device["yeelight_id"] = next_bulb_id
                    changed = True

        if changed:
            self._persist_devices()
        return matched

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

    def _yeelight_get_device_status(self, device: dict[str, Any]) -> dict[str, Any]:
        ip = str(device.get("ip", ""))
        status = self._yeelight_get_status(ip)
        if status.get("reachable", False):
            return status
        if not self._is_yeelight_transport_error(status.get("error", None)):
            return status
        matched = self._reconcile_yeelight_devices()
        bulb = matched.get(str(device.get("id", "")), None)
        next_ip = str(device.get("ip", "")).strip()
        if next_ip and next_ip != ip:
            retry = self._yeelight_get_status(next_ip)
            if retry.get("reachable", False):
                return retry
            status = retry
        if bulb is None:
            return status
        discovery_state = bulb.get("state", {})
        if isinstance(discovery_state, dict) and discovery_state:
            return {
                "reachable": True,
                "state": discovery_state,
                "error": "live state via discovery",
            }
        return status

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
            status = self._yeelight_get_device_status(device)
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
            if not ok and self._is_yeelight_transport_error(error):
                self._reconcile_yeelight_devices()
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
