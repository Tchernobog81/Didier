"""Integration probes and cached snapshot orchestration for system routes."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from dataclasses import field
from pathlib import Path
from typing import Any
from typing import Awaitable
from typing import Callable
from urllib.parse import urlparse

import httpx


def dedupe_urls(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = str(raw or "").strip().rstrip("/")
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def host_port(base_url: str) -> tuple[str, int] | None:
    raw = str(base_url or "").strip()
    if not raw:
        return None
    parsed = urlparse(raw)
    if not parsed.hostname:
        return None
    if parsed.port:
        return parsed.hostname, int(parsed.port)
    if parsed.scheme == "https":
        return parsed.hostname, 443
    return parsed.hostname, 80


async def probe_tcp(base_url: str, *, timeout_s: float = 2.0) -> dict[str, Any]:
    resolved = host_port(base_url)
    if resolved is None:
        return {"ok": False, "error": "invalid_url"}
    host, port = resolved
    started = time.perf_counter()
    try:
        connection = asyncio.open_connection(host=host, port=port)
        reader, writer = await asyncio.wait_for(connection, timeout=float(timeout_s))
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        _ = reader
        return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000.0, 1)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def http_probe(url: str, *, timeout_s: float = 2.0) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        timeout = httpx.Timeout(float(timeout_s))
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            response = await client.get(url)
        latency_ms = round((time.perf_counter() - started) * 1000.0, 1)
        payload: Any = None
        try:
            payload = response.json()
        except Exception:
            payload = None
        return {
            "ok": True,
            "status_code": int(response.status_code),
            "latency_ms": latency_ms,
            "json": payload,
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def resolve_signal_base_url(
    runtime_config_path: Path,
    *,
    env_get: Callable[[str, str], str] = os.getenv,
) -> str:
    env_value = str(env_get("DIDIER_SIGNAL_BASE_URL", "")).strip()
    if env_value:
        return env_value
    try:
        payload = json.loads(runtime_config_path.read_text(encoding="utf-8"))
        signal_cfg = payload.get("signal", {}) if isinstance(payload, dict) else {}
        http_url = signal_cfg.get("base_url", None) if isinstance(signal_cfg, dict) else None
        if http_url:
            return str(http_url).strip()
    except Exception:
        pass
    return "http://127.0.0.1:8082"


def safe_model_names(payload: dict[str, Any] | None, limit: int = 6) -> list[str]:
    if not isinstance(payload, dict):
        return []
    models = payload.get("models", None)
    if not isinstance(models, list):
        return []
    names: list[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if name:
            names.append(name)
        if len(names) >= limit:
            break
    return names


async def probe_ollama(
    orchestrator: Any,
    *,
    http_probe_fn: Callable[..., Awaitable[dict[str, Any]]] = http_probe,
    env_get: Callable[[str, str], str] = os.getenv,
) -> dict[str, Any]:
    configured = str(orchestrator.config.get("ollama.base_url", "http://127.0.0.1:11434")).strip()
    host_from_env = str(env_get("OLLAMA_HOST", "")).strip()
    env_url = str(env_get("DIDIER_OLLAMA_URL", "")).strip()
    host_url = f"http://{host_from_env}" if host_from_env else ""
    candidates = dedupe_urls(
        [configured, env_url, host_url, "http://127.0.0.1:11434", "http://127.0.0.1:11435"]
    )
    last_error = "no candidate"
    checks: list[dict[str, Any]] = []
    for base in candidates:
        endpoint = f"{base}/api/tags"
        result = await http_probe_fn(endpoint)
        check = {
            "base_url": base,
            "ok": bool(result.get("ok", False)),
            "status_code": result.get("status_code", None),
            "latency_ms": result.get("latency_ms", None),
            "error": result.get("error", None),
        }
        checks.append(check)
        if not result.get("ok", False):
            last_error = str(result.get("error", "unreachable"))
            continue
        status_code = int(result.get("status_code", 0))
        if status_code >= 500:
            last_error = f"http {status_code}"
            continue
        payload = result.get("json", None)
        names = safe_model_names(payload if isinstance(payload, dict) else None)
        model_count = 0
        if isinstance(payload, dict) and isinstance(payload.get("models"), list):
            model_count = len(payload["models"])
        status = "running" if status_code == 200 else "degraded"
        return {
            "status": status,
            "detail": f"http {status_code}",
            "base_url": base,
            "latency_ms": result.get("latency_ms", None),
            "model_count": model_count,
            "models": names,
            "checks": checks,
        }
    return {
        "status": "offline",
        "detail": last_error,
        "base_url": candidates[0] if candidates else configured,
        "latency_ms": None,
        "model_count": 0,
        "models": [],
        "checks": checks,
    }


async def probe_signal(
    *,
    runtime_config_path: Path,
    tcp_probe_fn: Callable[..., Awaitable[dict[str, Any]]] = probe_tcp,
    http_probe_fn: Callable[..., Awaitable[dict[str, Any]]] = http_probe,
    env_get: Callable[[str, str], str] = os.getenv,
) -> dict[str, Any]:
    base_url = resolve_signal_base_url(runtime_config_path, env_get=env_get).rstrip("/")
    tcp = await tcp_probe_fn(base_url)
    probe = await http_probe_fn(base_url)
    if probe.get("ok", False):
        status_code = int(probe.get("status_code", 0))
        status = "running" if tcp.get("ok", False) else "degraded"
        return {
            "status": status,
            "detail": f"http {status_code}",
            "base_url": base_url,
            "latency_ms": probe.get("latency_ms", None),
            "tcp_ok": bool(tcp.get("ok", False)),
            "http_status": status_code,
        }
    if tcp.get("ok", False):
        return {
            "status": "degraded",
            "detail": str(probe.get("error", "http probe failed")),
            "base_url": base_url,
            "latency_ms": tcp.get("latency_ms", None),
            "tcp_ok": True,
            "http_status": None,
        }
    return {
        "status": "offline",
        "detail": str(probe.get("error", tcp.get("error", "signal unavailable"))),
        "base_url": base_url,
        "latency_ms": None,
        "tcp_ok": False,
        "http_status": None,
    }


async def probe_picobot(
    orchestrator: Any,
    *,
    repo_root: Path,
    service_state: Callable[[str], Awaitable[tuple[bool, str]]],
    http_probe_fn: Callable[..., Awaitable[dict[str, Any]]] = http_probe,
) -> dict[str, Any]:
    cfg = orchestrator.config.get("picobot", {}) if orchestrator else {}
    if not isinstance(cfg, dict):
        cfg = {}
    enabled = bool(cfg.get("enabled", False))
    raw_config_path = str(cfg.get("config_path", "picobot_data/config.json")).strip()
    config_path = Path(raw_config_path)
    if not config_path.is_absolute():
        config_path = (repo_root / config_path).resolve()
    config_exists = config_path.exists()
    configured_tools_count = 0
    enabled_configured_tools_count = 0
    configured_tools: list[dict[str, Any]] = []
    model_name = str(cfg.get("llm_model", "")).strip()
    if config_exists:
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            tools = data.get("tools", []) if isinstance(data, dict) else []
            if isinstance(tools, list):
                for item in tools:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    if not name:
                        continue
                    configured_tools.append(
                        {
                            "name": name,
                            "enabled": bool(item.get("enabled", True)),
                            "type": str(item.get("type", "http")).strip() or "http",
                            "method": str(item.get("method", "GET")).strip().upper() or "GET",
                            "endpoint": (
                                str(item.get("endpoint") or item.get("url") or "").strip() or None
                            ),
                        }
                    )
                configured_tools_count = len(configured_tools)
                enabled_configured_tools_count = sum(
                    1 for item in configured_tools if bool(item.get("enabled", False))
                )
            llm = data.get("llm", {}) if isinstance(data, dict) else {}
            if not model_name and isinstance(llm, dict):
                model_name = str(llm.get("model", "")).strip()
        except Exception:
            pass

    builtin_tools: list[str] = []
    expected_builtin_tools: list[str] = []
    missing_builtin_tools: list[str] = []
    builtin_tools_count = 0
    expected_builtin_tools_count = 0
    install_required = False
    tools_source = "config_only"
    tool_scan_error: str | None = None
    bridge_base = str(cfg.get("bridge_url", "http://127.0.0.1:3901")).strip().rstrip("/")
    if not bridge_base:
        bridge_base = "http://127.0.0.1:3901"

    candidates = ("didier-picobot.service", "picobot.service")
    service_states: list[dict[str, Any]] = []
    running_service = ""
    for service_name in candidates:
        active, state = await service_state(service_name)
        service_states.append({"service": service_name, "active": active, "state": state})
        if active and not running_service:
            running_service = service_name

    if running_service:
        tools_probe = await http_probe_fn(f"{bridge_base}/tools")
        payload = tools_probe.get("json", None)
        if (
            tools_probe.get("ok", False)
            and int(tools_probe.get("status_code", 0)) < 500
            and isinstance(payload, dict)
        ):
            raw_builtin = payload.get("builtin_tools", [])
            if isinstance(raw_builtin, list):
                builtin_tools = sorted({str(item).strip() for item in raw_builtin if str(item).strip()})
            raw_expected = payload.get("expected_builtin_tools", [])
            if isinstance(raw_expected, list):
                expected_builtin_tools = sorted(
                    {str(item).strip() for item in raw_expected if str(item).strip()}
                )
            raw_missing = payload.get("missing_builtin_tools", [])
            if isinstance(raw_missing, list):
                missing_builtin_tools = sorted(
                    {str(item).strip() for item in raw_missing if str(item).strip()}
                )
            raw_configured = payload.get("configured_tools", [])
            if isinstance(raw_configured, list) and raw_configured:
                configured_tools = []
                for item in raw_configured:
                    if not isinstance(item, dict):
                        continue
                    name = str(item.get("name", "")).strip()
                    if not name:
                        continue
                    configured_tools.append(
                        {
                            "name": name,
                            "enabled": bool(item.get("enabled", True)),
                            "type": str(item.get("type", "http")).strip() or "http",
                            "method": str(item.get("method", "GET")).strip().upper() or "GET",
                            "endpoint": str(item.get("endpoint", "")).strip() or None,
                        }
                    )
            configured_tools_count = int(payload.get("configured_tools_count", len(configured_tools)) or 0)
            enabled_configured_tools_count = int(
                payload.get(
                    "enabled_configured_tools_count",
                    sum(1 for item in configured_tools if bool(item.get("enabled", False))),
                )
                or 0
            )
            builtin_tools_count = int(payload.get("builtin_tools_count", len(builtin_tools)) or 0)
            expected_builtin_tools_count = int(
                payload.get("expected_builtin_tools_count", len(expected_builtin_tools) or 0) or 0
            )
            install_required = bool(payload.get("install_required", False))
            tools_source = str(payload.get("source", "bridge")).strip() or "bridge"
            raw_scan_error = payload.get("scan_error", None)
            if raw_scan_error in (None, "", "None", "null"):
                tool_scan_error = None
            else:
                tool_scan_error = str(raw_scan_error).strip() or None
        elif tools_probe.get("ok", False):
            tool_scan_error = f"invalid /tools payload: http {tools_probe.get('status_code')}"
        else:
            tool_scan_error = str(tools_probe.get("error", "tools probe failed"))

    if not builtin_tools_count and builtin_tools:
        builtin_tools_count = len(builtin_tools)
    if not expected_builtin_tools_count and expected_builtin_tools:
        expected_builtin_tools_count = len(expected_builtin_tools)
    effective_tools_count = builtin_tools_count or configured_tools_count

    payload = {
        "enabled": enabled,
        "configured": config_exists,
        "config_path": str(config_path),
        "model": model_name or None,
        "tools_count": effective_tools_count,
        "configured_tools_count": configured_tools_count,
        "enabled_configured_tools_count": enabled_configured_tools_count,
        "configured_tools": configured_tools,
        "builtin_tools_count": builtin_tools_count,
        "builtin_tools": builtin_tools,
        "expected_builtin_tools_count": expected_builtin_tools_count,
        "expected_builtin_tools": expected_builtin_tools,
        "missing_builtin_tools": missing_builtin_tools,
        "install_required": install_required,
        "tools_source": tools_source,
        "tool_scan_error": tool_scan_error,
        "bridge_base_url": bridge_base,
        "service": running_service or None,
        "service_states": service_states,
    }
    if running_service:
        return {"status": "running", "detail": running_service, **payload}
    if enabled and config_exists:
        return {"status": "degraded", "detail": "configured but runtime unmanaged", **payload}
    return {"status": "offline", "detail": "not configured", **payload}


def integration_state_score(status: str) -> int:
    normalized = str(status or "").lower()
    if "run" in normalized or "ok" in normalized:
        return 2
    if "degrad" in normalized or "warn" in normalized:
        return 1
    return 0


def rollup_status(values: list[str]) -> str:
    scores = [integration_state_score(value) for value in values]
    if all(score >= 2 for score in scores):
        return "running"
    if any(score == 0 for score in scores):
        if any(score >= 2 for score in scores):
            return "degraded"
        return "offline"
    return "degraded"


@dataclass(frozen=True)
class IntegrationsSnapshotDeps:
    get_orchestrator: Callable[[], Any]
    service_state: Callable[[str], Awaitable[tuple[bool, str]]]
    runtime_config_path: Path
    repo_root: Path


@dataclass
class IntegrationsSnapshotCollector:
    cache_ttl_s: float
    now: Callable[[], float] = time.time
    probe_picobot_fn: Callable[..., Awaitable[dict[str, Any]]] = probe_picobot
    probe_ollama_fn: Callable[..., Awaitable[dict[str, Any]]] = probe_ollama
    probe_signal_fn: Callable[..., Awaitable[dict[str, Any]]] = probe_signal
    _cache: dict[str, Any] | None = None
    _cache_ts: float = 0.0
    _lock: Any = field(default_factory=asyncio.Lock)

    async def collect(self, *, force: bool, deps: IntegrationsSnapshotDeps) -> dict[str, Any]:
        now = float(self.now())
        if not force and self._cache is not None and (now - self._cache_ts) <= self.cache_ttl_s:
            return dict(self._cache)
        if self._lock.locked() and self._cache is not None and not force:
            return dict(self._cache)

        async with self._lock:
            now = float(self.now())
            if not force and self._cache is not None and (now - self._cache_ts) <= self.cache_ttl_s:
                return dict(self._cache)
            try:
                orchestrator = deps.get_orchestrator()
            except Exception:
                orchestrator = None

            if orchestrator is None:
                payload = {
                    "ts": float(self.now()),
                    "status": "offline",
                    "picobot": {"status": "offline", "detail": "orchestrator unavailable"},
                    "ollama": {"status": "offline", "detail": "orchestrator unavailable"},
                    "signal": {"status": "offline", "detail": "orchestrator unavailable"},
                }
                self._cache = dict(payload)
                self._cache_ts = float(self.now())
                return payload

            picobot, ollama, signal = await asyncio.gather(
                self.probe_picobot_fn(
                    orchestrator,
                    repo_root=deps.repo_root,
                    service_state=deps.service_state,
                ),
                self.probe_ollama_fn(orchestrator),
                self.probe_signal_fn(runtime_config_path=deps.runtime_config_path),
            )
            payload = {
                "ts": float(self.now()),
                "status": rollup_status(
                    [
                        str(picobot.get("status", "")),
                        str(ollama.get("status", "")),
                        str(signal.get("status", "")),
                    ]
                ),
                "picobot": picobot,
                "ollama": ollama,
                "signal": signal,
            }
            self._cache = dict(payload)
            self._cache_ts = float(self.now())
            return payload
