import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from core.config import DidierConfig
from core.hardware_aware import get_best_model as llmfit_get_best_model
from core.resource_arbitrator import get_resource_arbitrator
from core.shared_state import metrics_snapshot
from core.shared_state import read_state as read_shared_state
from shared.ipc import request as ipc_request

router = APIRouter()
DEFAULT_TIMEOUT_S = 2.0

_EDGE_WORKERS = (
    {
        "name": "didier-api",
        "service": "api",
        "label": "Worker API",
        "fallback_base": "http://127.0.0.1:5010",
        "meta": "FastAPI 5010",
        "worker_type": "gateway",
        "ipc": "unix+http",
    },
    {
        "name": "didier-vision",
        "service": "vision",
        "label": "Worker Vision",
        "fallback_base": "http://127.0.0.1:5011",
        "meta": "Vision 5011",
        "worker_type": "perception",
        "ipc": "unix",
    },
    {
        "name": "didier-brain",
        "service": "brain",
        "label": "Worker Brain",
        "fallback_base": "http://127.0.0.1:5012",
        "meta": "Brain 5012",
        "worker_type": "cognition",
        "ipc": "unix",
    },
    {
        "name": "didier-audio",
        "service": "audio",
        "label": "Worker Audio",
        "fallback_base": "http://127.0.0.1:5013",
        "meta": "Audio/TTS 5013",
        "worker_type": "audio",
        "ipc": "unix",
    },
    {
        "name": "didier-asr",
        "service": "asr",
        "label": "Worker ASR",
        "fallback_base": "http://127.0.0.1:5014",
        "meta": "Wake/ASR 5014",
        "worker_type": "speech",
        "ipc": "unix+http",
    },
    {
        "name": "didier-picobot",
        "service": "picobot",
        "label": "Worker Picobot",
        "fallback_base": "http://127.0.0.1:3901",
        "meta": "Agent léger local",
        "worker_type": "agentic",
        "ipc": "http",
    },
)

_EDGE_LINKS = (
    {"from": "edge-dashboard", "to": "edge-api", "mode": "sync", "label": "HTTP"},
    {"from": "edge-vscode", "to": "edge-api", "mode": "sync", "label": "HTTP"},
    {"from": "edge-api", "to": "edge-worker-didier-api", "mode": "sync", "label": "loopback"},
    {"from": "edge-api", "to": "edge-worker-didier-vision", "mode": "sync", "label": "RPC"},
    {"from": "edge-api", "to": "edge-worker-didier-brain", "mode": "sync", "label": "RPC"},
    {"from": "edge-api", "to": "edge-worker-didier-audio", "mode": "async", "label": "queue"},
    {"from": "edge-api", "to": "edge-worker-didier-asr", "mode": "async", "label": "stream"},
    {"from": "edge-worker-didier-asr", "to": "edge-worker-didier-brain", "mode": "async", "label": "transcript"},
    {"from": "edge-worker-didier-brain", "to": "edge-worker-didier-audio", "mode": "async", "label": "tts"},
    {"from": "edge-api", "to": "edge-worker-didier-picobot", "mode": "async", "label": "proxy"},
    {"from": "edge-worker-didier-brain", "to": "edge-worker-didier-picobot", "mode": "async", "label": "react"},
    {"from": "edge-worker-didier-brain", "to": "edge-didier-model", "mode": "sync", "label": "LLM"},
    {"from": "edge-worker-didier-picobot", "to": "edge-didier-model", "mode": "sync", "label": "LLM"},
    {"from": "edge-api", "to": "edge-camera", "mode": "sync", "label": "vision"},
    {"from": "edge-api", "to": "edge-camera-secondary", "mode": "async", "label": "stream"},
    {"from": "edge-api", "to": "edge-audio", "mode": "async", "label": "audio"},
    {"from": "edge-api", "to": "edge-tts", "mode": "async", "label": "tts"},
    {"from": "edge-api", "to": "edge-npu", "mode": "sync", "label": "PCIe"},
    {"from": "edge-worker-didier-vision", "to": "edge-camera", "mode": "sync", "label": "capture"},
    {"from": "edge-worker-didier-vision", "to": "edge-npu", "mode": "sync", "label": "infer"},
    {"from": "edge-worker-didier-audio", "to": "edge-audio", "mode": "async", "label": "out"},
    {"from": "edge-worker-didier-audio", "to": "edge-tts", "mode": "async", "label": "tts"},
)

_TERMINAL_REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNTIME_CONFIG_PATH = (_TERMINAL_REPO_ROOT / "config" / "config.json").resolve()
_TERMINAL_MAX_CHARS = 300
_TERMINAL_MAX_OUTPUT = 12000
_TERMINAL_BLOCKED_SNIPPETS = (
    "rm -rf /",
    "mkfs",
    "shutdown",
    "reboot",
    "poweroff",
)
_METRICS_WS_INTERVAL_S = max(
    0.5, min(float(os.getenv("DIDIER_METRICS_WS_INTERVAL_S", "1.0")), 5.0)
)
_DEVICE_STATUS_CACHE_TTL_S = max(
    0.5, min(float(os.getenv("DIDIER_DEVICE_STATUS_CACHE_TTL_S", "3.0")), 10.0)
)
_DEVICE_STATUS_CACHE: dict[str, Any] | None = None
_DEVICE_STATUS_CACHE_TS = 0.0
_DEVICE_STATUS_LOCK = asyncio.Lock()
_PERIPHERAL_SPECS: dict[str, dict[str, str]] = {
    "video": {
        "label": "Flux video",
        "kind": "sense",
        "channel": "video",
        "service": "didier-vision.service",
    },
    "sound": {
        "label": "Sortie son",
        "kind": "actionneur",
        "channel": "audio",
        "service": "didier-audio.service",
    },
    "mic": {
        "label": "Entree micro",
        "kind": "sense",
        "channel": "audio",
        "service": "didier-asr.service",
    },
    "wifi": {
        "label": "Connecteur reseau",
        "kind": "connectivite",
        "channel": "wifi",
        "service": "didier-api.service",
    },
}
_INTEGRATIONS_CACHE_TTL_S = max(
    1.0, min(float(os.getenv("DIDIER_INTEGRATIONS_CACHE_TTL_S", "3.0")), 20.0)
)
_INTEGRATIONS_CACHE: dict[str, Any] | None = None
_INTEGRATIONS_CACHE_TS = 0.0
_INTEGRATIONS_LOCK = asyncio.Lock()
_LLMFIT_CACHE_TTL_S = max(
    2.0, min(float(os.getenv("DIDIER_LLMFIT_REPORT_CACHE_TTL_S", "12.0")), 60.0)
)
_LLMFIT_CACHE: dict[str, Any] | None = None
_LLMFIT_CACHE_TS = 0.0
_LLMFIT_LOCK = asyncio.Lock()
_CONFIG_WRITE_LOCK = asyncio.Lock()
_MODEL_SELECTABLE_TASKS = {"chat", "coding", "react_task"}
_LLMFIT_TASK_SAMPLES: tuple[tuple[str, str], ...] = (
    ("chat", "Bonjour Didier, fais un point rapide du systeme."),
    ("coding", "Ecris une fonction Python fibonacci iterative."),
    ("vision", "Detecte les objets visibles dans le flux camera."),
    ("asr", "Transcrire une commande vocale courte."),
    ("tts", "Synthese vocale courte et claire."),
    ("react_task", "Allume la lumiere du salon."),
)


def _fallback_metrics_payload() -> dict[str, Any]:
    return {
        "timestamp": time.time(),
        "cpu": {"percent": 0.0, "temp_c": None, "per_core": []},
        "memory": {"total": 0, "used": 0, "percent": 0.0},
        "disk": {
            "root": {"available": False, "path": "/"},
            "ssd": {"available": False, "path": "/mnt/didier_ssd"},
        },
        "npu": {
            "available": False,
            "device": False,
            "pcie": False,
            "utilization": None,
            "active": False,
            "core_count": 0,
            "cores": [],
        },
        "audio": {"available": False, "level_percent": 0, "listening": False},
        "workers": {},
        "source": "shared_state_v1",
    }


async def _run_systemctl(*args: str) -> tuple[int, str]:
    cmd = ["sudo", "-n", "systemctl", *args]

    def _run() -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=DEFAULT_TIMEOUT_S,
        )

    proc = await asyncio.to_thread(_run)
    detail = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, detail


async def _service_state(service: str) -> tuple[bool, str]:
    rc, detail = await _run_systemctl("is-active", service)
    state = (detail or "unknown").splitlines()[0].strip().lower()
    if rc == 0 and state in {"active", "activating"}:
        return True, state
    if not state:
        state = "inactive"
    return False, state


def _wifi_link_state() -> str:
    oper_path = Path("/sys/class/net/wlan0/operstate")
    if oper_path.exists():
        try:
            return oper_path.read_text(encoding="utf-8").strip().lower() or "unknown"
        except Exception:
            return "unknown"
    return "not-present"


async def _peripheral_item(key: str, spec: dict[str, str]) -> dict[str, Any]:
    service = spec["service"]
    active, state = await _service_state(service)
    item: dict[str, Any] = {
        "id": key,
        "label": spec["label"],
        "kind": spec["kind"],
        "channel": spec["channel"],
        "service": service,
        "active": active,
        "state": state,
    }
    if key == "wifi":
        item["link_state"] = _wifi_link_state()
    return item

async def _probe_worker_health(service: str, fallback_base: str) -> tuple[str, str]:
    if service == "api":
        return "ok", "loopback"
    if service == "picobot":
        integrations = await _collect_integrations_snapshot()
        picobot = integrations.get("picobot", {}) if isinstance(integrations, dict) else {}
        status = str(picobot.get("status", "offline"))
        detail = str(picobot.get("detail", "picobot unavailable"))
        return status, detail
    try:
        response = await ipc_request(
            "GET",
            "/health",
            service=service,
            base_url=fallback_base,
            timeout=min(0.8, DEFAULT_TIMEOUT_S),
        )
        if not response.is_success:
            return "offline", f"http {response.status_code}"
        payload = response.json()
        status = str(payload.get("status", "ok")).lower()
        detail = payload.get("detail") or payload.get("service") or payload.get("name") or "online"
        detail_text = str(detail)
        if len(detail_text) > 160:
            detail_text = detail_text[:157].rstrip() + "..."
        return status, detail_text
    except Exception as exc:
        return "offline", str(exc)


def _dedupe_urls(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = str(raw or "").strip().rstrip("/")
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _host_port(base_url: str) -> tuple[str, int] | None:
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


async def _probe_tcp(base_url: str) -> dict[str, Any]:
    host_port = _host_port(base_url)
    if host_port is None:
        return {"ok": False, "error": "invalid_url"}
    host, port = host_port
    started = time.perf_counter()
    try:
        connection = asyncio.open_connection(host=host, port=port)
        reader, writer = await asyncio.wait_for(connection, timeout=DEFAULT_TIMEOUT_S)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        _ = reader
        return {"ok": True, "latency_ms": round((time.perf_counter() - started) * 1000.0, 1)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


async def _http_probe(url: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        timeout = httpx.Timeout(DEFAULT_TIMEOUT_S)
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


def _resolve_signal_base_url() -> str:
    env = str(os.getenv("DIDIER_SIGNAL_BASE_URL", "")).strip()
    if env:
        return env
    cfg_path = _RUNTIME_CONFIG_PATH
    try:
        payload = json.loads(cfg_path.read_text(encoding="utf-8"))
        signal_cfg = payload.get("signal", {}) if isinstance(payload, dict) else {}
        http_url = signal_cfg.get("base_url", None) if isinstance(signal_cfg, dict) else None
        if http_url:
            return str(http_url).strip()
    except Exception:
        pass
    return "http://127.0.0.1:8082"


def _safe_model_names(payload: dict[str, Any] | None, limit: int = 6) -> list[str]:
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


async def _probe_ollama(orchestrator: Any) -> dict[str, Any]:
    configured = str(orchestrator.config.get("ollama.base_url", "http://127.0.0.1:11434")).strip()
    host_from_env = str(os.getenv("OLLAMA_HOST", "")).strip()
    env_url = str(os.getenv("DIDIER_OLLAMA_URL", "")).strip()
    host_url = f"http://{host_from_env}" if host_from_env else ""
    candidates = _dedupe_urls(
        [configured, env_url, host_url, "http://127.0.0.1:11434", "http://127.0.0.1:11435"]
    )
    last_error = "no candidate"
    checks: list[dict[str, Any]] = []
    for base in candidates:
        endpoint = f"{base}/api/tags"
        result = await _http_probe(endpoint)
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
        names = _safe_model_names(payload if isinstance(payload, dict) else None)
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


async def _probe_signal() -> dict[str, Any]:
    base_url = _resolve_signal_base_url().rstrip("/")
    tcp = await _probe_tcp(base_url)
    probe = await _http_probe(base_url)
    if probe.get("ok", False):
        status_code = int(probe.get("status_code", 0))
        status = "running" if tcp.get("ok", False) else "degraded"
        detail = f"http {status_code}"
        return {
            "status": status,
            "detail": detail,
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


async def _probe_picobot(orchestrator: Any) -> dict[str, Any]:
    cfg = orchestrator.config.get("picobot", {}) if orchestrator else {}
    if not isinstance(cfg, dict):
        cfg = {}
    enabled = bool(cfg.get("enabled", False))
    raw_config_path = str(cfg.get("config_path", "picobot_data/config.json")).strip()
    config_path = Path(raw_config_path)
    if not config_path.is_absolute():
        config_path = (_TERMINAL_REPO_ROOT / config_path).resolve()
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
                    entry = {
                        "name": name,
                        "enabled": bool(item.get("enabled", True)),
                        "type": str(item.get("type", "http")).strip() or "http",
                        "method": str(item.get("method", "GET")).strip().upper() or "GET",
                        "endpoint": str(item.get("endpoint") or item.get("url") or "").strip() or None,
                    }
                    configured_tools.append(entry)
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
    for service in candidates:
        active, state = await _service_state(service)
        service_states.append({"service": service, "active": active, "state": state})
        if active and not running_service:
            running_service = service

    if running_service:
        tools_probe = await _http_probe(f"{bridge_base}/tools")
        payload = tools_probe.get("json", None)
        if (
            tools_probe.get("ok", False)
            and int(tools_probe.get("status_code", 0)) < 500
            and isinstance(payload, dict)
        ):
            raw_builtin = payload.get("builtin_tools", [])
            if isinstance(raw_builtin, list):
                builtin_tools = sorted(
                    {
                        str(item).strip()
                        for item in raw_builtin
                        if str(item).strip()
                    }
                )
            raw_expected = payload.get("expected_builtin_tools", [])
            if isinstance(raw_expected, list):
                expected_builtin_tools = sorted(
                    {
                        str(item).strip()
                        for item in raw_expected
                        if str(item).strip()
                    }
                )
            raw_missing = payload.get("missing_builtin_tools", [])
            if isinstance(raw_missing, list):
                missing_builtin_tools = sorted(
                    {
                        str(item).strip()
                        for item in raw_missing
                        if str(item).strip()
                    }
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

    if running_service:
        return {
            "status": "running",
            "detail": running_service,
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
            "service": running_service,
            "service_states": service_states,
        }
    if enabled and config_exists:
        return {
            "status": "degraded",
            "detail": "configured but runtime unmanaged",
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
            "service": None,
            "service_states": service_states,
        }
    return {
        "status": "offline",
        "detail": "not configured",
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
        "service": None,
        "service_states": service_states,
    }


def _integration_state_score(status: str) -> int:
    normalized = str(status or "").lower()
    if "run" in normalized or "ok" in normalized:
        return 2
    if "degrad" in normalized or "warn" in normalized:
        return 1
    return 0


def _rollup_status(values: list[str]) -> str:
    scores = [_integration_state_score(value) for value in values]
    if all(score >= 2 for score in scores):
        return "running"
    if any(score == 0 for score in scores):
        if any(score >= 2 for score in scores):
            return "degraded"
        return "offline"
    return "degraded"


async def _collect_integrations_snapshot(force: bool = False) -> dict[str, Any]:
    global _INTEGRATIONS_CACHE, _INTEGRATIONS_CACHE_TS
    now = time.time()
    if (
        not force
        and _INTEGRATIONS_CACHE is not None
        and (now - _INTEGRATIONS_CACHE_TS) <= _INTEGRATIONS_CACHE_TTL_S
    ):
        return dict(_INTEGRATIONS_CACHE)
    if _INTEGRATIONS_LOCK.locked() and _INTEGRATIONS_CACHE is not None and not force:
        return dict(_INTEGRATIONS_CACHE)

    async with _INTEGRATIONS_LOCK:
        now = time.time()
        if (
            not force
            and _INTEGRATIONS_CACHE is not None
            and (now - _INTEGRATIONS_CACHE_TS) <= _INTEGRATIONS_CACHE_TTL_S
        ):
            return dict(_INTEGRATIONS_CACHE)
        from core import runtime_bridge as api_module

        orchestrator = None
        try:
            orchestrator = api_module._require_orchestrator()
        except Exception:
            orchestrator = None

        if orchestrator is None:
            payload = {
                "ts": time.time(),
                "status": "offline",
                "picobot": {"status": "offline", "detail": "orchestrator unavailable"},
                "ollama": {"status": "offline", "detail": "orchestrator unavailable"},
                "signal": {"status": "offline", "detail": "orchestrator unavailable"},
            }
            _INTEGRATIONS_CACHE = dict(payload)
            _INTEGRATIONS_CACHE_TS = time.time()
            return payload

        picobot, ollama, signal = await asyncio.gather(
            _probe_picobot(orchestrator),
            _probe_ollama(orchestrator),
            _probe_signal(),
        )
        status = _rollup_status(
            [str(picobot.get("status", "")), str(ollama.get("status", "")), str(signal.get("status", ""))]
        )
        payload = {
            "ts": time.time(),
            "status": status,
            "picobot": picobot,
            "ollama": ollama,
            "signal": signal,
        }
        _INTEGRATIONS_CACHE = dict(payload)
        _INTEGRATIONS_CACHE_TS = time.time()
        return payload


def _llmfit_score_bucket(score: str) -> str:
    normalized = str(score or "").strip().lower()
    if "perfect" in normalized:
        return "perfect"
    if "good" in normalized:
        return "good"
    if "marginal" in normalized:
        return "marginal"
    return "fallback"


def _llmfit_reason_excerpt(reason: str, limit: int = 220) -> str:
    text = str(reason or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _llmfit_context_from_state(state: dict[str, Any]) -> dict[str, Any]:
    metrics = state.get("metrics", {}) if isinstance(state, dict) else {}
    hardware_profile = state.get("hardware_profile", {}) if isinstance(state, dict) else {}
    npu = hardware_profile.get("npu", {}) if isinstance(hardware_profile, dict) else {}
    tpu = hardware_profile.get("tpu", {}) if isinstance(hardware_profile, dict) else {}
    cpu = metrics.get("cpu", {}) if isinstance(metrics, dict) else {}
    memory = metrics.get("memory", {}) if isinstance(metrics, dict) else {}
    context: dict[str, Any] = {
        "npu_available": bool(npu.get("available", False)),
        "npu_device_count": int(npu.get("device_count", 0) or 0),
        "pixel_detected": bool(tpu.get("pixel_detected", False)),
        "pixel_count": int(tpu.get("pixel_count", 0) or 0),
        "cpu_percent": float(cpu.get("percent", 0.0) or 0.0),
        "memory_percent": float(memory.get("percent", 0.0) or 0.0),
    }
    return context


def _llmfit_recommendation(
    task_type: str,
    prompt_sample: str,
    base_context: dict[str, Any],
) -> dict[str, Any]:
    context = dict(base_context)
    context["prompt_preview"] = str(prompt_sample or "")[:120]
    context["task_sample"] = str(task_type or "")
    result = llmfit_get_best_model(task_type, context)
    score = str(result.get("score", "good")).strip().lower()
    return {
        "task_type": str(task_type or "").strip() or "chat",
        "prompt_sample": str(prompt_sample or ""),
        "backend": str(result.get("backend", "")).strip(),
        "model": str(result.get("model", "")).strip(),
        "score": score or "good",
        "score_bucket": _llmfit_score_bucket(score),
        "provider": str(result.get("provider", "llmfit")).strip() or "llmfit",
        "source": str(result.get("source", "fallback")).strip() or "fallback",
        "reason": _llmfit_reason_excerpt(str(result.get("reason", ""))),
        "timeout_s": float(result.get("timeout_s", DEFAULT_TIMEOUT_S) or DEFAULT_TIMEOUT_S),
        "ts": float(result.get("ts", time.time()) or time.time()),
    }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalize_task_type(value: Any) -> str:
    return str(value or "").strip().lower()


def _read_runtime_config() -> dict[str, Any]:
    if not _RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(_RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_runtime_config(payload: dict[str, Any]) -> None:
    _RUNTIME_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _RUNTIME_CONFIG_PATH.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(_RUNTIME_CONFIG_PATH)


def _build_current_models_payload(config_root: dict[str, Any]) -> dict[str, Any]:
    root = _as_dict(config_root)
    ollama_cfg = _as_dict(root.get("ollama"))
    profiles = _as_dict(ollama_cfg.get("model_profiles"))
    llmfit_cfg = _as_dict(root.get("llmfit"))
    llmfit_profiles = _as_dict(llmfit_cfg.get("task_profiles"))
    llmfit_models: dict[str, dict[str, Any]] = {}
    for task_name in ("chat", "coding", "react_task", "vision", "asr", "tts"):
        task_cfg = _as_dict(llmfit_profiles.get(task_name))
        if not task_cfg:
            continue
        llmfit_models[task_name] = {
            "backend": str(task_cfg.get("backend", "")).strip() or None,
            "model": str(task_cfg.get("model", "")).strip() or None,
            "score": str(task_cfg.get("score", "")).strip() or None,
        }
    return {
        "default": str(ollama_cfg.get("model", "")).strip() or None,
        "ask": str(profiles.get("ask", "")).strip() or None,
        "coding": str(profiles.get("coding", "")).strip() or None,
        "selected_at": float(ollama_cfg.get("model_selected_at", 0.0) or 0.0),
        "llmfit_profiles": llmfit_models,
    }


def _find_llmfit_recommendation(
    report: dict[str, Any],
    task_type: str,
    model: str,
) -> dict[str, Any] | None:
    normalized_task = _normalize_task_type(task_type)
    normalized_model = str(model or "").strip()
    if not normalized_task or not normalized_model:
        return None
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        return None
    for entry in recommendations:
        if not isinstance(entry, dict):
            continue
        task_entry = _normalize_task_type(entry.get("task_type"))
        model_entry = str(entry.get("model", "")).strip()
        if task_entry == normalized_task and model_entry == normalized_model:
            return dict(entry)
    return None


def _invalidate_model_caches() -> None:
    global _DEVICE_STATUS_CACHE, _DEVICE_STATUS_CACHE_TS, _LLMFIT_CACHE, _LLMFIT_CACHE_TS
    _DEVICE_STATUS_CACHE = None
    _DEVICE_STATUS_CACHE_TS = 0.0
    _LLMFIT_CACHE = None
    _LLMFIT_CACHE_TS = 0.0


async def _collect_llmfit_report(force: bool = False) -> dict[str, Any]:
    global _LLMFIT_CACHE, _LLMFIT_CACHE_TS
    now = time.time()
    if (
        not force
        and _LLMFIT_CACHE is not None
        and (now - _LLMFIT_CACHE_TS) <= _LLMFIT_CACHE_TTL_S
    ):
        return dict(_LLMFIT_CACHE)
    if _LLMFIT_LOCK.locked() and _LLMFIT_CACHE is not None and not force:
        return dict(_LLMFIT_CACHE)

    async with _LLMFIT_LOCK:
        now = time.time()
        if (
            not force
            and _LLMFIT_CACHE is not None
            and (now - _LLMFIT_CACHE_TS) <= _LLMFIT_CACHE_TTL_S
        ):
            return dict(_LLMFIT_CACHE)
        try:
            state = read_shared_state()
            hardware_profile = (
                state.get("hardware_profile", {})
                if isinstance(state, dict)
                else {}
            )
            base_context = _llmfit_context_from_state(state if isinstance(state, dict) else {})
            jobs = [
                asyncio.to_thread(_llmfit_recommendation, task, prompt, base_context)
                for task, prompt in _LLMFIT_TASK_SAMPLES
            ]
            recommendations = await asyncio.gather(*jobs)
            bucket_counts: dict[str, int] = {
                "perfect": 0,
                "good": 0,
                "marginal": 0,
                "fallback": 0,
            }
            llmfit_hits = 0
            fallback_hits = 0
            for item in recommendations:
                bucket = str(item.get("score_bucket", "fallback"))
                if bucket not in bucket_counts:
                    bucket = "fallback"
                bucket_counts[bucket] += 1
                if str(item.get("source", "")) == "llmfit":
                    llmfit_hits += 1
                else:
                    fallback_hits += 1

            status = "running" if llmfit_hits > 0 else "degraded"
            payload = {
                "ok": True,
                "ts": time.time(),
                "status": status,
                "provider": "llmfit",
                "cache_ttl_s": _LLMFIT_CACHE_TTL_S,
                "summary": {
                    "tasks_total": len(recommendations),
                    "llmfit_hits": llmfit_hits,
                    "fallback_hits": fallback_hits,
                    **bucket_counts,
                },
                "hardware_profile": hardware_profile if isinstance(hardware_profile, dict) else {},
                "recommendations": recommendations,
            }
        except Exception as exc:
            payload = {
                "ok": False,
                "ts": time.time(),
                "status": "offline",
                "provider": "llmfit",
                "cache_ttl_s": _LLMFIT_CACHE_TTL_S,
                "summary": {
                    "tasks_total": 0,
                    "llmfit_hits": 0,
                    "fallback_hits": 0,
                    "perfect": 0,
                    "good": 0,
                    "marginal": 0,
                    "fallback": 0,
                },
                "hardware_profile": {},
                "recommendations": [],
                "error": str(exc),
            }
        _LLMFIT_CACHE = dict(payload)
        _LLMFIT_CACHE_TS = time.time()
        return payload


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "name": "Didier"}


@router.get("/version")
async def version() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    return api_module._read_version()


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    snapshot = metrics_snapshot()
    if snapshot:
        return snapshot
    return _fallback_metrics_payload()


@router.get("/system/arbitration")
async def system_arbitration() -> dict[str, Any]:
    arbitrator = get_resource_arbitrator()
    return arbitrator.snapshot()


@router.get("/system/integrations")
async def system_integrations(refresh: bool = False) -> dict[str, Any]:
    return await _collect_integrations_snapshot(force=bool(refresh))


@router.get("/hardware/llmfit")
async def hardware_llmfit(refresh: bool = False) -> dict[str, Any]:
    return await _collect_llmfit_report(force=bool(refresh))


@router.get("/hardware/models/current")
async def hardware_models_current() -> dict[str, Any]:
    config_root = _read_runtime_config()
    return {
        "ok": True,
        "ts": time.time(),
        "config_path": str(_RUNTIME_CONFIG_PATH),
        "current": _build_current_models_payload(config_root),
    }


@router.post("/hardware/models/select")
async def hardware_models_select(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {}
    task_type = _normalize_task_type(body.get("task_type"))
    model = str(body.get("model", "")).strip()
    backend = str(body.get("backend", "")).strip() or None
    allow_unbenchmarked = bool(body.get("allow_unbenchmarked", False))

    if not task_type:
        raise HTTPException(status_code=400, detail="task_type required")
    if task_type not in _MODEL_SELECTABLE_TASKS:
        raise HTTPException(
            status_code=400,
            detail=f"task_type not selectable: {task_type}",
        )
    if not model:
        raise HTTPException(status_code=400, detail="model required")
    if len(model) > 160 or any(ch in model for ch in ("\n", "\r", "\x00")):
        raise HTTPException(status_code=400, detail="invalid model value")

    llmfit_report = await _collect_llmfit_report(force=False)
    recommendation = _find_llmfit_recommendation(llmfit_report, task_type, model)
    if recommendation is None and not allow_unbenchmarked:
        raise HTTPException(
            status_code=400,
            detail="model must come from current llmfit recommendations",
        )

    async with _CONFIG_WRITE_LOCK:
        config_root = _read_runtime_config()
        if not config_root:
            raise HTTPException(status_code=503, detail="runtime config unavailable")

        llmfit_cfg = _as_dict(config_root.setdefault("llmfit", {}))
        llmfit_profiles = _as_dict(llmfit_cfg.setdefault("task_profiles", {}))
        task_profile = _as_dict(llmfit_profiles.setdefault(task_type, {}))
        task_profile["model"] = model
        if backend:
            task_profile["backend"] = backend
        elif recommendation is not None:
            task_profile["backend"] = str(recommendation.get("backend", "")).strip() or task_profile.get("backend")
        if recommendation is not None:
            score = str(recommendation.get("score", "")).strip()
            if score:
                task_profile["score"] = score
        llmfit_profiles[task_type] = task_profile
        llmfit_cfg["task_profiles"] = llmfit_profiles
        config_root["llmfit"] = llmfit_cfg

        ollama_cfg = _as_dict(config_root.setdefault("ollama", {}))
        model_profiles = _as_dict(ollama_cfg.setdefault("model_profiles", {}))
        if task_type in {"chat", "react_task"}:
            model_profiles["ask"] = model
            ollama_cfg["model"] = model
        elif task_type == "coding":
            model_profiles["coding"] = model
        ollama_cfg["model_profiles"] = model_profiles
        ollama_cfg["model_selected_at"] = time.time()
        config_root["ollama"] = ollama_cfg

        _write_runtime_config(config_root)

    from core import runtime_bridge as api_module

    try:
        orchestrator = api_module._require_orchestrator()
        orchestrator._config = DidierConfig.load(_RUNTIME_CONFIG_PATH)
    except Exception:
        pass

    _invalidate_model_caches()
    updated = _build_current_models_payload(_read_runtime_config())
    return {
        "ok": True,
        "ts": time.time(),
        "applied": {
            "task_type": task_type,
            "model": model,
            "backend": backend or (str(recommendation.get("backend", "")).strip() if recommendation else None),
            "benchmarked": recommendation is not None,
            "score": str(recommendation.get("score", "")).strip() if recommendation else None,
        },
        "current": updated,
    }


@router.websocket("/ws/metrics")
async def ws_metrics(websocket: WebSocket) -> None:
    from core import runtime_bridge as api_module

    await websocket.accept()
    try:
        while True:
            snapshot = metrics_snapshot() or _fallback_metrics_payload()
            asr_payload = api_module._read_asr_status()
            await websocket.send_json(
                {
                    "type": "metrics_update",
                    "ts": time.time(),
                    "metrics": snapshot,
                    "asr": asr_payload,
                }
            )
            await asyncio.sleep(_METRICS_WS_INTERVAL_S)
    except WebSocketDisconnect:
        return
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


@router.get("/device-status")
async def device_status() -> dict[str, Any]:
    global _DEVICE_STATUS_CACHE, _DEVICE_STATUS_CACHE_TS
    now = time.time()
    if (
        _DEVICE_STATUS_CACHE is not None
        and (now - _DEVICE_STATUS_CACHE_TS) <= _DEVICE_STATUS_CACHE_TTL_S
    ):
        return dict(_DEVICE_STATUS_CACHE)
    if _DEVICE_STATUS_LOCK.locked() and _DEVICE_STATUS_CACHE is not None:
        return dict(_DEVICE_STATUS_CACHE)

    async with _DEVICE_STATUS_LOCK:
        now = time.time()
        if (
            _DEVICE_STATUS_CACHE is not None
            and (now - _DEVICE_STATUS_CACHE_TS) <= _DEVICE_STATUS_CACHE_TTL_S
        ):
            return dict(_DEVICE_STATUS_CACHE)

        from core import runtime_bridge as api_module

        orchestrator = api_module._require_orchestrator()
        camera_index = int(orchestrator.config.get("vision.camera_index", 0))
        camera_device = orchestrator.config.get("vision.camera_device", None)
        vendor = orchestrator.config.get("vision.usb_id_vendor", None)
        product = orchestrator.config.get("vision.usb_id_product", None)
        sink = orchestrator.config.get("bluetooth.sink_name", "")
        tts_model = orchestrator.config.get("tts.model_path", None)
        tts_config = orchestrator.config.get("tts.config_path", None)
        tts_voices = orchestrator.config.get("tts.voices_path", None)
        npu_device = orchestrator.config.get("npu.device", "/dev/hailo0")
        npu_pcie = orchestrator.config.get("npu.pcie_address", "0001:01:00.0")
        didier_model = (
            orchestrator.config.get("ollama.model_profiles.ask", None)
            or orchestrator.config.get("ollama.ask_model", None)
            or orchestrator.config.get("ollama.model", None)
        )
        secondary_cfg = orchestrator.config.get("vision.remote_stream", {}) or {}
        secondary_enabled = bool(secondary_cfg.get("enabled", True))

        vision = orchestrator.get_tentacle("vision")
        camera = None
        if vision and hasattr(vision, "get_status"):
            try:
                status = vision.get_status()
                last_frame_ts = status.get("last_frame_ts")
                age = now - last_frame_ts if last_frame_ts else None
                ok = age is not None and age < 3.5
                camera = {
                    "device": camera_device or f"index:{camera_index}",
                    "opened": bool(ok),
                    "frame": bool(ok),
                    "last_frame_ts": last_frame_ts,
                    "last_frame_age_s": round(age, 2) if age is not None else None,
                    "source": "vision",
                }
            except Exception:
                camera = None
        if camera is None:
            camera = await api_module.asyncio.to_thread(
                api_module._check_camera, camera_index, camera_device
            )
        camera_secondary: dict[str, Any] = {
            "enabled": secondary_enabled,
            "opened": False,
            "frame": False,
            "last_frame_ts": None,
            "last_frame_age_s": None,
            "source": "remote_stream",
        }
        if secondary_enabled:
            stream = None
            with api_module._REMOTE_STREAM_LOCK:
                stream = api_module._REMOTE_STREAM
            if stream is not None:
                try:
                    frame, last_frame_ts = stream.get_last()
                    age = time.time() - last_frame_ts if last_frame_ts else None
                    camera_secondary.update(
                        {
                            "opened": True,
                            "frame": bool(frame),
                            "last_frame_ts": last_frame_ts,
                            "last_frame_age_s": round(age, 2) if age is not None else None,
                        }
                    )
                except Exception:
                    pass
        camera_usb = await api_module.asyncio.to_thread(
            api_module._check_camera_usb, vendor, product
        )
        mic = await api_module.asyncio.to_thread(api_module._check_camera_mic)
        sound = await api_module.asyncio.to_thread(api_module._check_soundboks_sink, sink)
        npu = await api_module.asyncio.to_thread(
            api_module._check_npu, npu_device, npu_pcie
        )
        tts = await api_module.asyncio.to_thread(
            api_module._check_tts, tts_model, tts_config, tts_voices
        )
        version = await api_module.asyncio.to_thread(api_module._read_version)

        payload = {
            "camera": camera,
            "camera_secondary": camera_secondary,
            "camera_usb": camera_usb,
            "mic": mic,
            "sound": sound,
            "npu": npu,
            "tts": tts,
            "version": version,
            "models": {
                "didier": didier_model,
                # Backward-compat for older UIs still expecting a clawbot key.
                "clawbot": didier_model,
                "ask": orchestrator.config.get("ollama.model_profiles.ask", None),
                "coding": orchestrator.config.get("ollama.model_profiles.coding", None),
            },
        }
        _DEVICE_STATUS_CACHE = dict(payload)
        _DEVICE_STATUS_CACHE_TS = time.time()
        return payload


@router.get("/peripherals")
async def peripherals() -> dict[str, Any]:
    items = await asyncio.gather(
        *[_peripheral_item(key, spec) for key, spec in _PERIPHERAL_SPECS.items()]
    )
    return {
        "ok": True,
        "ts": time.time(),
        "items": items,
    }


@router.post("/peripherals/toggle")
async def peripherals_toggle(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = payload or {}
    peripheral_id = str(body.get("id", "")).strip().lower()
    if peripheral_id not in _PERIPHERAL_SPECS:
        raise HTTPException(status_code=400, detail="unknown peripheral id")

    spec = _PERIPHERAL_SPECS[peripheral_id]
    service = spec["service"]
    current_active, current_state = await _service_state(service)

    requested_enabled: bool | None = None
    if "enabled" in body:
        requested_enabled = bool(body.get("enabled"))
    else:
        action = str(body.get("action", "")).strip().lower()
        if action in {"start", "on", "enable"}:
            requested_enabled = True
        elif action in {"stop", "off", "disable"}:
            requested_enabled = False

    if requested_enabled is None:
        requested_enabled = not current_active

    cmd = "start" if requested_enabled else "stop"
    rc, detail = await _run_systemctl(cmd, service)
    if rc != 0:
        raise HTTPException(
            status_code=500,
            detail=f"systemctl {cmd} failed for {service}: {detail or f'rc={rc}'}",
        )

    active, state = await _service_state(service)
    item = await _peripheral_item(peripheral_id, spec)
    return {
        "ok": True,
        "ts": time.time(),
        "id": peripheral_id,
        "service": service,
        "requested": cmd,
        "before": {"active": current_active, "state": current_state},
        "after": {"active": active, "state": state},
        "detail": detail,
        "item": item,
    }


@router.get("/docker/diagram")
async def docker_diagram() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    try:
        containers = await api_module.asyncio.to_thread(api_module._read_docker_containers)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}")
    health_results = await asyncio.gather(
        *[_probe_worker_health(item["service"], item["fallback_base"]) for item in _EDGE_WORKERS]
    )
    workers: list[dict[str, Any]] = []
    for item, (status, detail) in zip(_EDGE_WORKERS, health_results):
        workers.append(
            {
                "name": item["name"],
                "label": item["label"],
                "status": status,
                "meta": item["meta"],
                "detail": detail,
                "worker_type": item.get("worker_type", "edge"),
                "ipc": item.get("ipc", "unix"),
            }
        )
    return {
        "ts": time.time(),
        "containers": containers,
        "workers": workers,
        "links": list(_EDGE_LINKS),
    }


@router.get("/files/search")
async def files_search(q: str = "") -> dict[str, Any]:
    from core import runtime_bridge as api_module

    query = str(q or "").strip()
    if len(query) < 2:
        return {"results": []}
    results = await api_module.asyncio.to_thread(api_module._search_repo_files, query)
    return {"results": results}


@router.post("/terminal/exec")
async def terminal_exec(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    command = str((payload or {}).get("command", "")).strip()
    if not command:
        raise HTTPException(status_code=400, detail="command required")
    if len(command) > _TERMINAL_MAX_CHARS:
        raise HTTPException(status_code=400, detail="command too long")
    if any(char in command for char in ("\n", "\r", "\x00")):
        raise HTTPException(status_code=400, detail="multiline command not allowed")
    lower_command = command.lower()
    if any(snippet in lower_command for snippet in _TERMINAL_BLOCKED_SNIPPETS):
        raise HTTPException(status_code=400, detail="command blocked")
    timeout_s = DEFAULT_TIMEOUT_S
    started = time.time()
    try:
        proc = await asyncio.to_thread(
            subprocess.run,
            ["bash", "-lc", command],
            cwd=str(_TERMINAL_REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="command timeout")
    output = f"{proc.stdout or ''}{proc.stderr or ''}".strip()
    if len(output) > _TERMINAL_MAX_OUTPUT:
        output = output[:_TERMINAL_MAX_OUTPUT].rstrip() + "\n...[truncated]"
    return {
        "ok": proc.returncode == 0,
        "command": command,
        "exit_code": proc.returncode,
        "elapsed_ms": int((time.time() - started) * 1000),
        "output": output,
        "cwd": str(_TERMINAL_REPO_ROOT),
    }


@router.get("/camera/holders")
async def camera_holders() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    return await api_module.asyncio.to_thread(api_module._camera_holders, camera_device)


@router.post("/camera/reconnect")
async def camera_reconnect() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    return await api_module.asyncio.to_thread(api_module._camera_reconnect, camera_device)


@router.post("/camera/force-format")
async def camera_force_format() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    orchestrator = api_module._require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    width = orchestrator.config.get("vision.width", None)
    height = orchestrator.config.get("vision.height", None)
    fourcc = orchestrator.config.get("vision.fourcc", None)
    return await api_module.asyncio.to_thread(
        api_module._camera_force_format, camera_device, width, height, fourcc
    )
