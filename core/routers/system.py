import asyncio
import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from core.hardware_aware import get_best_model as llmfit_get_best_model
from core.resource_arbitrator import get_resource_arbitrator
from core.shared_state import metrics_snapshot
from core.shared_state import read_state as read_shared_state
from core.system_camera_service import CameraControlConfig
from core.system_camera_service import camera_force_format_payload
from core.system_camera_service import camera_holders_payload
from core.system_camera_service import camera_reconnect_payload
from core.system_integrations_service import IntegrationsSnapshotCollector
from core.system_integrations_service import IntegrationsSnapshotDeps
from core.system_device_status_service import DeviceStatusCollector
from core.system_device_status_service import DeviceStatusDeps
from core.system_llmfit_service import DEFAULT_LLMFIT_TASK_SAMPLES
from core.system_llmfit_service import LLMFitReportCollector
from core.system_model_selection_service import ModelSelectionError
from core.system_model_selection_service import apply_model_selection
from core.system_model_selection_service import build_current_models_payload
from core.system_model_selection_service import find_llmfit_recommendation
from core.system_model_selection_service import parse_model_selection_request
from core.system_model_selection_service import read_runtime_config
from core.system_model_selection_service import write_runtime_config
from core.system_service_control import run_systemctl
from core.system_service_control import service_state
from core.system_peripherals_service import PeripheralServiceError
from core.system_peripherals_service import SystemPeripheralsDeps
from core.system_peripherals_service import collect_peripherals
from core.system_peripherals_service import toggle_peripheral
from core.system_terminal_service import TerminalExecError
from core.system_terminal_service import execute_terminal_command
from core.system_terminal_service import parse_terminal_command
from core.system_workers_service import WorkerHealthDeps
from core.system_workers_service import build_docker_diagram_payload
from core.system_workers_service import collect_edge_workers
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
_DEVICE_STATUS_COLLECTOR = DeviceStatusCollector(cache_ttl_s=_DEVICE_STATUS_CACHE_TTL_S)
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
_INTEGRATIONS_COLLECTOR = IntegrationsSnapshotCollector(cache_ttl_s=_INTEGRATIONS_CACHE_TTL_S)
_LLMFIT_CACHE_TTL_S = max(
    2.0, min(float(os.getenv("DIDIER_LLMFIT_REPORT_CACHE_TTL_S", "12.0")), 60.0)
)
_CONFIG_WRITE_LOCK = asyncio.Lock()
_MODEL_SELECTABLE_TASKS = {"chat", "coding", "react_task"}
_LLMFIT_COLLECTOR = LLMFitReportCollector(
    cache_ttl_s=_LLMFIT_CACHE_TTL_S,
    task_samples=DEFAULT_LLMFIT_TASK_SAMPLES,
    read_shared_state_fn=read_shared_state,
    get_best_model_fn=llmfit_get_best_model,
    default_timeout_s=DEFAULT_TIMEOUT_S,
    now=time.time,
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


def _service_state_dep():
    return lambda service: service_state(service, timeout_s=DEFAULT_TIMEOUT_S)


def _run_systemctl_dep():
    return lambda cmd, service: run_systemctl(cmd, service, timeout_s=DEFAULT_TIMEOUT_S)


def _peripherals_deps() -> SystemPeripheralsDeps:
    return SystemPeripheralsDeps(
        now=time.time,
        service_state=_service_state_dep(),
        run_systemctl=_run_systemctl_dep(),
    )


def _worker_health_deps() -> WorkerHealthDeps:
    return WorkerHealthDeps(
        integrations_snapshot=lambda: _collect_integrations_snapshot(),
        ipc_health=lambda service, base_url, timeout_s: ipc_request(
            "GET",
            "/health",
            service=service,
            base_url=base_url,
            timeout=timeout_s,
        ),
        timeout_s=min(0.8, DEFAULT_TIMEOUT_S),
    )


def _device_status_deps(api_module: Any) -> DeviceStatusDeps:
    def _get_remote_stream():
        with api_module._REMOTE_STREAM_LOCK:
            return api_module._REMOTE_STREAM

    return DeviceStatusDeps(
        get_orchestrator=api_module._require_orchestrator,
        now=time.time,
        get_remote_stream=_get_remote_stream,
        check_camera=lambda camera_index, camera_device: api_module.asyncio.to_thread(
            api_module._check_camera,
            camera_index,
            camera_device,
        ),
        check_camera_usb=lambda vendor, product: api_module.asyncio.to_thread(
            api_module._check_camera_usb,
            vendor,
            product,
        ),
        check_camera_mic=lambda: api_module.asyncio.to_thread(api_module._check_camera_mic),
        check_soundboks_sink=lambda sink: api_module.asyncio.to_thread(
            api_module._check_soundboks_sink,
            sink,
        ),
        check_npu=lambda npu_device, npu_pcie: api_module.asyncio.to_thread(
            api_module._check_npu,
            npu_device,
            npu_pcie,
        ),
        check_tts=lambda tts_model, tts_config, tts_voices: api_module.asyncio.to_thread(
            api_module._check_tts,
            tts_model,
            tts_config,
            tts_voices,
        ),
        read_version=lambda: api_module.asyncio.to_thread(api_module._read_version),
    )


def _camera_control_config(api_module: Any) -> CameraControlConfig:
    orchestrator = api_module._require_orchestrator()
    return CameraControlConfig.from_config(orchestrator.config)


async def _collect_integrations_snapshot(force: bool = False) -> dict[str, Any]:
    from core import runtime_bridge as api_module

    return await _INTEGRATIONS_COLLECTOR.collect(
        force=bool(force),
        deps=IntegrationsSnapshotDeps(
            get_orchestrator=api_module._require_orchestrator,
            service_state=_service_state_dep(),
            runtime_config_path=_RUNTIME_CONFIG_PATH,
            repo_root=_TERMINAL_REPO_ROOT,
        ),
    )


def _invalidate_model_caches() -> None:
    _DEVICE_STATUS_COLLECTOR.invalidate()
    _LLMFIT_COLLECTOR.invalidate()


async def _collect_llmfit_report(force: bool = False) -> dict[str, Any]:
    return await _LLMFIT_COLLECTOR.collect(force=bool(force))


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
    config_root = read_runtime_config(_RUNTIME_CONFIG_PATH)
    return {
        "ok": True,
        "ts": time.time(),
        "config_path": str(_RUNTIME_CONFIG_PATH),
        "current": build_current_models_payload(config_root),
    }


@router.post("/hardware/models/select")
async def hardware_models_select(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        request = parse_model_selection_request(
            payload,
            selectable_tasks=_MODEL_SELECTABLE_TASKS,
        )
    except ModelSelectionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)

    llmfit_report = await _collect_llmfit_report(force=False)
    recommendation = find_llmfit_recommendation(llmfit_report, request.task_type, request.model)
    if recommendation is None and not request.allow_unbenchmarked:
        raise HTTPException(
            status_code=400,
            detail="model must come from current llmfit recommendations",
        )

    async with _CONFIG_WRITE_LOCK:
        config_root = read_runtime_config(_RUNTIME_CONFIG_PATH)
        try:
            updated_root, applied = apply_model_selection(
                config_root,
                request,
                recommendation,
                selected_at=time.time(),
            )
        except ModelSelectionError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail)
        write_runtime_config(_RUNTIME_CONFIG_PATH, updated_root)

    from core import runtime_bridge as api_module

    try:
        orchestrator = api_module._require_orchestrator()
        orchestrator.reload_config(_RUNTIME_CONFIG_PATH)
    except Exception:
        pass

    _invalidate_model_caches()
    updated = build_current_models_payload(read_runtime_config(_RUNTIME_CONFIG_PATH))
    return {
        "ok": True,
        "ts": time.time(),
        "applied": applied,
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
    from core import runtime_bridge as api_module

    return await _DEVICE_STATUS_COLLECTOR.collect(deps=_device_status_deps(api_module))


@router.get("/peripherals")
async def peripherals() -> dict[str, Any]:
    return await collect_peripherals(_PERIPHERAL_SPECS, deps=_peripherals_deps())


@router.post("/peripherals/toggle")
async def peripherals_toggle(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        return await toggle_peripheral(payload, _PERIPHERAL_SPECS, deps=_peripherals_deps())
    except PeripheralServiceError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/docker/diagram")
async def docker_diagram() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    try:
        containers = await api_module.asyncio.to_thread(api_module._read_docker_containers)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}")
    workers = await collect_edge_workers(_EDGE_WORKERS, deps=_worker_health_deps())
    return build_docker_diagram_payload(
        containers=containers,
        workers=workers,
        links=_EDGE_LINKS,
        now=time.time(),
    )


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
    try:
        command = parse_terminal_command(
            payload,
            max_chars=_TERMINAL_MAX_CHARS,
            blocked_snippets=_TERMINAL_BLOCKED_SNIPPETS,
        )
        return await asyncio.to_thread(
            execute_terminal_command,
            command,
            repo_root=_TERMINAL_REPO_ROOT,
            timeout_s=DEFAULT_TIMEOUT_S,
            max_output_chars=_TERMINAL_MAX_OUTPUT,
            now=time.time,
        )
    except TerminalExecError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("/camera/holders")
async def camera_holders() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    config = _camera_control_config(api_module)
    return await camera_holders_payload(
        config,
        camera_holders_fn=lambda camera_device: api_module.asyncio.to_thread(
            api_module._camera_holders,
            camera_device,
        ),
    )


@router.post("/camera/reconnect")
async def camera_reconnect() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    config = _camera_control_config(api_module)
    return await camera_reconnect_payload(
        config,
        camera_reconnect_fn=lambda camera_device: api_module.asyncio.to_thread(
            api_module._camera_reconnect,
            camera_device,
        ),
    )


@router.post("/camera/force-format")
async def camera_force_format() -> dict[str, Any]:
    from core import runtime_bridge as api_module

    config = _camera_control_config(api_module)
    return await camera_force_format_payload(
        config,
        camera_force_format_fn=lambda camera_device, width, height, fourcc: api_module.asyncio.to_thread(
            api_module._camera_force_format,
            camera_device,
            width,
            height,
            fourcc,
        ),
    )
