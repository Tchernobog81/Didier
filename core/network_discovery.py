"""Passive hardware and network discovery for SharedState hardware_profile."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

import psutil

from core.hailo.monitor import detect_hailo

DEFAULT_SCAN_INTERVAL_S = max(
    2.0,
    min(float(os.getenv("DIDIER_HW_DISCOVERY_INTERVAL_S", "8.0")), 120.0),
)
DEFAULT_SUBPROCESS_TIMEOUT_S = 2.0
DEFAULT_PIXEL_NAME_PATTERNS = (
    "pixel",
    "pixel-10",
    "pixel_10",
)
_NEIGHBOR_FAILED_STATES = {"FAILED", "INCOMPLETE"}

CommandRunner = Callable[[list[str], float], tuple[int, str, str]]


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _is_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except Exception:
        return False


def _normalize_mac(value: str) -> str:
    cleaned = str(value or "").strip().replace("-", ":").lower()
    if not cleaned:
        return ""
    parts = [chunk.zfill(2) for chunk in cleaned.split(":") if chunk]
    if len(parts) < 3:
        return ""
    return ":".join(parts)


def parse_ip_neigh_output(raw: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for line in (raw or "").splitlines():
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        ip = parts[0].strip()
        if not _is_ipv4(ip):
            continue
        state = str(parts[-1]).strip().upper() if parts else "UNKNOWN"
        iface = ""
        mac = ""
        if "dev" in parts:
            idx = parts.index("dev")
            if idx + 1 < len(parts):
                iface = parts[idx + 1]
        if "lladdr" in parts:
            idx = parts.index("lladdr")
            if idx + 1 < len(parts):
                mac = _normalize_mac(parts[idx + 1])
        items.append(
            {
                "ip": ip,
                "interface": iface or None,
                "mac": mac or None,
                "neighbor_state": state,
                "alive": state not in _NEIGHBOR_FAILED_STATES,
            }
        )
    items.sort(key=lambda item: str(item.get("ip", "")))
    return items


def parse_avahi_browse_output(raw: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for line in (raw or "").splitlines():
        row = line.strip()
        if not row or row[0] not in {"=", "+"}:
            continue
        parts = row.split(";")
        if len(parts) < 6:
            continue
        iface = parts[1].strip()
        name = parts[3].strip()
        service = parts[4].strip()
        host = parts[6].strip() if len(parts) > 6 else ""
        address = parts[7].strip() if len(parts) > 7 else ""
        port_raw = parts[8].strip() if len(parts) > 8 else ""
        port: int | None = None
        try:
            if port_raw:
                port = int(port_raw)
        except Exception:
            port = None
        if address and not _is_ipv4(address):
            address = ""
        entries.append(
            {
                "interface": iface or None,
                "name": name or None,
                "service": service or None,
                "host": host or None,
                "address": address or None,
                "port": port,
            }
        )
    entries.sort(
        key=lambda item: (
            str(item.get("address") or ""),
            str(item.get("host") or ""),
            str(item.get("service") or ""),
        )
    )
    return entries


def _default_command_runner(cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=max(0.1, min(float(timeout_s), DEFAULT_SUBPROCESS_TIMEOUT_S)),
        )
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    except Exception as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _read_board_model() -> str:
    candidates = (
        Path("/proc/device-tree/model"),
        Path("/sys/firmware/devicetree/base/model"),
    )
    for path in candidates:
        try:
            if path.exists():
                value = path.read_text(encoding="utf-8", errors="replace").replace(
                    "\x00", ""
                )
                text = value.strip()
                if text:
                    return text
        except Exception:
            continue
    return ""


def _safe_detect_hailo() -> bool:
    try:
        return bool(detect_hailo())
    except Exception:
        return False


def _safe_local_ipv4_addrs() -> set[str]:
    values: set[str] = set()
    try:
        for _, entries in psutil.net_if_addrs().items():
            for entry in entries:
                if getattr(entry, "family", None) != socket.AF_INET:
                    continue
                ip = str(getattr(entry, "address", "") or "").strip()
                if _is_ipv4(ip):
                    values.add(ip)
    except Exception:
        return set()
    return values


def _fingerprint_profile(profile: Mapping[str, Any]) -> str:
    # Keep fingerprint stable across volatile neighbor churn (ARP/mDNS state flips).
    stable = {
        "schema": str(profile.get("schema", "didier.hardware_profile.v1")),
        "source": str(profile.get("source", "network_discovery_v1")),
        "host": _as_mapping(profile.get("host")),
        "cpu": _as_mapping(profile.get("cpu")),
        "ram": _as_mapping(profile.get("ram")),
        "npu": _as_mapping(profile.get("npu")),
        "tpu": _as_mapping(profile.get("tpu")),
    }
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


class NetworkDiscovery:
    """Passive discovery scanner with on-change profile diffing."""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        command_runner: CommandRunner | None = None,
        now_fn: Callable[[], float] | None = None,
        hailo_probe: Callable[[], bool] | None = None,
    ) -> None:
        cfg = _as_mapping(config)
        self._logger = logging.getLogger("NetworkDiscovery")
        self._scan_interval_s = max(
            2.0,
            min(
                _as_float(cfg.get("interval_seconds", DEFAULT_SCAN_INTERVAL_S), DEFAULT_SCAN_INTERVAL_S),
                120.0,
            ),
        )
        self._enable_arp = _as_bool(cfg.get("enable_arp", True), default=True)
        self._enable_mdns = _as_bool(cfg.get("enable_mdns", True), default=True)
        self._pixel_ip_hints = {
            str(item).strip()
            for item in _as_list(cfg.get("pixel_ip_hints"))
            if str(item).strip()
        }
        self._pixel_mac_prefixes = {
            _normalize_mac(str(item)).replace(":", "")[:6]
            for item in _as_list(cfg.get("pixel_mac_prefixes"))
            if _normalize_mac(str(item))
        }
        raw_patterns = [
            str(item).strip()
            for item in _as_list(cfg.get("pixel_name_patterns", list(DEFAULT_PIXEL_NAME_PATTERNS)))
            if str(item).strip()
        ]
        if not raw_patterns:
            raw_patterns = list(DEFAULT_PIXEL_NAME_PATTERNS)
        self._pixel_patterns = [
            re.compile(re.escape(pattern), flags=re.IGNORECASE)
            for pattern in raw_patterns
        ]
        self._command_runner = command_runner or _default_command_runner
        self._now_fn = now_fn or time.time
        self._hailo_probe = hailo_probe or _safe_detect_hailo

        self._state_lock = threading.Lock()
        self._last_scan_ts = 0.0
        self._last_fingerprint = ""
        self._last_profile: dict[str, Any] | None = None

    def _run_cmd(self, cmd: list[str]) -> tuple[int, str, str]:
        return self._command_runner(cmd, DEFAULT_SUBPROCESS_TIMEOUT_S)

    def _scan_neighbors(self) -> list[dict[str, Any]]:
        if not self._enable_arp:
            return []
        if shutil.which("ip") is None:
            return []
        rc, out, _ = self._run_cmd(["ip", "neigh", "show"])
        if rc != 0:
            return []
        return parse_ip_neigh_output(out)

    def _scan_mdns(self) -> list[dict[str, Any]]:
        if not self._enable_mdns:
            return []
        if shutil.which("avahi-browse") is None:
            return []
        rc, out, _ = self._run_cmd(["avahi-browse", "-art"])
        if rc != 0:
            return []
        return parse_avahi_browse_output(out)

    def _is_pixel_device(self, device: Mapping[str, Any]) -> bool:
        ip = str(device.get("ip") or "").strip()
        if ip and ip in self._pixel_ip_hints:
            return True

        mac = _normalize_mac(str(device.get("mac") or ""))
        if mac:
            prefix = mac.replace(":", "")[:6]
            if prefix and prefix in self._pixel_mac_prefixes:
                return True

        haystack_parts: list[str] = []
        for key in ("hostname", "name"):
            value = str(device.get(key) or "").strip()
            if value:
                haystack_parts.append(value)
        for key in ("services", "labels"):
            value = device.get(key)
            if isinstance(value, list):
                haystack_parts.extend(str(item) for item in value if str(item).strip())
        haystack = " ".join(haystack_parts).lower()
        if not haystack:
            return False
        return any(pattern.search(haystack) for pattern in self._pixel_patterns)

    def _merge_network_devices(
        self,
        neighbors: list[dict[str, Any]],
        mdns_entries: list[dict[str, Any]],
        local_ips: set[str],
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}

        def _entry_key(ip: str, host: str, name: str) -> str:
            if ip:
                return ip
            if host:
                return host
            if name:
                return name
            return f"unknown-{len(merged) + 1}"

        for item in neighbors:
            ip = str(item.get("ip") or "")
            if not ip or ip in local_ips:
                continue
            key = _entry_key(ip, "", "")
            entry = merged.setdefault(
                key,
                {
                    "id": key,
                    "ip": ip,
                    "hostname": None,
                    "name": None,
                    "mac": None,
                    "interface": None,
                    "neighbor_state": None,
                    "services": [],
                    "labels": [],
                    "origin": [],
                    "kind": "generic_device",
                },
            )
            entry["mac"] = item.get("mac") or entry.get("mac")
            entry["interface"] = item.get("interface") or entry.get("interface")
            entry["neighbor_state"] = item.get("neighbor_state") or entry.get(
                "neighbor_state"
            )
            if "arp" not in entry["origin"]:
                entry["origin"].append("arp")

        for item in mdns_entries:
            ip = str(item.get("address") or "")
            host = str(item.get("host") or "")
            name = str(item.get("name") or "")
            if ip and ip in local_ips:
                continue
            key = _entry_key(ip, host, name)
            entry = merged.setdefault(
                key,
                {
                    "id": key,
                    "ip": ip or None,
                    "hostname": None,
                    "name": None,
                    "mac": None,
                    "interface": None,
                    "neighbor_state": None,
                    "services": [],
                    "labels": [],
                    "origin": [],
                    "kind": "generic_device",
                },
            )
            if ip and not entry.get("ip"):
                entry["ip"] = ip
            if host:
                entry["hostname"] = host
            if name:
                entry["name"] = name
                if name not in entry["labels"]:
                    entry["labels"].append(name)
            service = str(item.get("service") or "").strip()
            if service and service not in entry["services"]:
                entry["services"].append(service)
            iface = item.get("interface")
            if iface:
                entry["interface"] = iface
            if "mdns" not in entry["origin"]:
                entry["origin"].append("mdns")

        devices = []
        for entry in merged.values():
            if self._is_pixel_device(entry):
                entry["kind"] = "pixel_tpu_candidate"
            else:
                text = " ".join(
                    [
                        str(entry.get("hostname") or ""),
                        str(entry.get("name") or ""),
                        " ".join(str(service) for service in entry.get("services", [])),
                    ]
                ).lower()
                if "hailo" in text:
                    entry["kind"] = "hailo_peer_candidate"
            devices.append(entry)

        devices.sort(
            key=lambda item: (
                str(item.get("kind") or ""),
                str(item.get("ip") or ""),
                str(item.get("hostname") or ""),
                str(item.get("id") or ""),
            )
        )
        return devices[:128]

    def _build_profile(self, now_ts: float) -> dict[str, Any]:
        board_model = _read_board_model()
        hostname = socket.gethostname()
        is_rpi = "raspberry pi" in board_model.lower()
        virtual = psutil.virtual_memory()
        npu_devices = sorted(str(path) for path in Path("/dev").glob("hailo*"))
        npu_available = bool(npu_devices) or bool(self._hailo_probe())

        neighbors = self._scan_neighbors()
        mdns_entries = self._scan_mdns()
        local_ips = _safe_local_ipv4_addrs()
        devices = self._merge_network_devices(neighbors, mdns_entries, local_ips)
        pixel_devices = [
            {
                "id": item.get("id"),
                "ip": item.get("ip"),
                "hostname": item.get("hostname"),
                "services": item.get("services", []),
            }
            for item in devices
            if item.get("kind") == "pixel_tpu_candidate"
        ]

        profile = {
            "schema": "didier.hardware_profile.v1",
            "source": "network_discovery_v1",
            "scanned_at": now_ts,
            "host": {
                "hostname": hostname,
                "board_model": board_model or None,
                "platform": platform.platform(),
                "arch": platform.machine(),
                "is_raspberry_pi": bool(is_rpi),
            },
            "cpu": {
                "logical_cores": int(psutil.cpu_count(logical=True) or 0),
                "physical_cores": int(psutil.cpu_count(logical=False) or 0),
            },
            "ram": {
                "total_bytes": int(virtual.total),
            },
            "npu": {
                "type": "hailo",
                "available": bool(npu_available),
                "device_count": len(npu_devices),
                "devices": npu_devices,
            },
            "tpu": {
                "pixel_detected": bool(pixel_devices),
                "pixel_count": len(pixel_devices),
                "pixel_devices": pixel_devices,
            },
            "network_devices": devices,
            "discovery": {
                "interval_seconds": self._scan_interval_s,
                "enable_arp": self._enable_arp,
                "enable_mdns": self._enable_mdns,
                "neighbors_count": len(neighbors),
                "mdns_count": len(mdns_entries),
            },
        }
        return profile

    def scan(self, force: bool = False) -> dict[str, Any]:
        now_ts = self._now_fn()
        with self._state_lock:
            if (
                not force
                and self._last_profile is not None
                and (now_ts - self._last_scan_ts) < self._scan_interval_s
            ):
                return {
                    "changed": False,
                    "cached": True,
                    "fingerprint": self._last_fingerprint,
                    "profile": json.loads(json.dumps(self._last_profile)),
                }

        profile = self._build_profile(now_ts)
        fingerprint = _fingerprint_profile(profile)
        with self._state_lock:
            changed = fingerprint != self._last_fingerprint
            self._last_scan_ts = now_ts
            self._last_fingerprint = fingerprint
            self._last_profile = profile
        if changed:
            self._logger.info(
                "hardware profile changed (npu=%s, pixel=%s, devices=%s)",
                bool(profile.get("npu", {}).get("available", False)),
                int(profile.get("tpu", {}).get("pixel_count", 0)),
                len(profile.get("network_devices", [])),
            )
        return {
            "changed": changed,
            "cached": False,
            "fingerprint": fingerprint,
            "profile": json.loads(json.dumps(profile)),
        }


_DISCOVERY_LOCK = threading.Lock()
_DISCOVERY_SINGLETON: NetworkDiscovery | None = None


def get_network_discovery(
    config: Mapping[str, Any] | None = None,
    *,
    refresh: bool = False,
) -> NetworkDiscovery:
    global _DISCOVERY_SINGLETON
    if refresh:
        with _DISCOVERY_LOCK:
            _DISCOVERY_SINGLETON = NetworkDiscovery(config=config)
            return _DISCOVERY_SINGLETON
    if _DISCOVERY_SINGLETON is None:
        with _DISCOVERY_LOCK:
            if _DISCOVERY_SINGLETON is None:
                _DISCOVERY_SINGLETON = NetworkDiscovery(config=config)
    return _DISCOVERY_SINGLETON


def scan_hardware_profile(
    config: Mapping[str, Any] | None = None,
    *,
    force: bool = False,
    refresh_scanner: bool = False,
) -> dict[str, Any]:
    scanner = get_network_discovery(config=config, refresh=refresh_scanner)
    return scanner.scan(force=force)
