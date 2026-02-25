"""Helpers to target local/remote Ollama endpoints safely."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import httpx

from core.shared_state import read_state as read_shared_state

DEFAULT_CONFIG_PATH = Path(os.getenv("DIDIER_CONFIG_PATH", "config/config.json"))
DEFAULT_OLLAMA_PORT = 11434
DEFAULT_TIMEOUT_S = 2.0


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    return {}


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_base_url(value: str) -> str:
    return str(value or "").strip().rstrip("/")


def _read_config(path: Path = DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_root_config(root_config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if root_config is not None:
        return _as_mapping(root_config)
    return _read_config()


def _routing_config(root: Mapping[str, Any]) -> dict[str, Any]:
    return _as_mapping(root.get("routing"))


def _pixel_ip_hints(root: Mapping[str, Any]) -> list[str]:
    hardware = _as_mapping(root.get("hardware"))
    discovery = _as_mapping(hardware.get("discovery"))
    return [str(item).strip() for item in _as_list(discovery.get("pixel_ip_hints")) if str(item).strip()]


def is_local_ollama_url(base_url: str) -> bool:
    parsed = urlparse(_normalize_base_url(base_url))
    host = str(parsed.hostname or "").strip().lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def resolve_pixel_ollama_base_url(
    *,
    root_config: Mapping[str, Any] | None = None,
    shared_state: Mapping[str, Any] | None = None,
) -> str | None:
    root = _read_root_config(root_config)
    routing = _routing_config(root)
    pixel_cfg = _as_mapping(routing.get("pixel_ollama"))
    if not _as_bool(pixel_cfg.get("enabled", True), default=True):
        return None

    configured_base = _normalize_base_url(str(pixel_cfg.get("base_url", "")))
    if configured_base:
        return configured_base

    port = max(1, min(_as_int(pixel_cfg.get("port", DEFAULT_OLLAMA_PORT), DEFAULT_OLLAMA_PORT), 65535))
    path = str(pixel_cfg.get("path", "")).strip()
    path = path.lstrip("/")

    state = _as_mapping(shared_state) or _as_mapping(read_shared_state())
    profile = _as_mapping(state.get("hardware_profile"))
    tpu = _as_mapping(profile.get("tpu"))
    pixel_devices = _as_list(tpu.get("pixel_devices"))
    candidates: list[str] = []

    for item in pixel_devices:
        node = _as_mapping(item)
        ip = str(node.get("ip", "")).strip()
        if ip:
            candidates.append(ip)

    if not candidates:
        for ip in _pixel_ip_hints(root):
            candidates.append(ip)

    if not candidates:
        network_devices = _as_list(profile.get("network_devices"))
        for item in network_devices:
            node = _as_mapping(item)
            if str(node.get("kind", "")).strip() != "pixel_tpu_candidate":
                continue
            ip = str(node.get("ip", "")).strip()
            if ip:
                candidates.append(ip)

    if not candidates:
        return None

    host = candidates[0]
    base = f"http://{host}:{port}"
    if path:
        return f"{base}/{path}"
    return base


async def probe_ollama_endpoint(
    base_url: str,
    *,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> tuple[bool, str, list[str]]:
    normalized = _normalize_base_url(base_url)
    if not normalized:
        return False, "empty_base_url", []
    url = f"{normalized}/api/tags"
    timeout = max(0.1, min(_as_float(timeout_s, DEFAULT_TIMEOUT_S), DEFAULT_TIMEOUT_S))
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return False, f"{type(exc).__name__}:{exc}", []

    models: list[str] = []
    for item in _as_list(_as_mapping(payload).get("models")):
        node = _as_mapping(item)
        name = str(node.get("name") or node.get("model") or "").strip()
        if name:
            models.append(name)
    return True, "ok", models
