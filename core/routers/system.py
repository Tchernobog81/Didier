import time
import asyncio
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from core.shared_state import metrics_snapshot
from shared.ipc import request as ipc_request

router = APIRouter()

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
        "name": "didier-openclaw",
        "service": "openclaw",
        "label": "Worker OpenClaw",
        "fallback_base": "http://127.0.0.1:3901",
        "meta": "Agent bridge 3901",
        "worker_type": "agentic",
        "ipc": "unix",
    },
)

_EDGE_LINKS = (
    {"from": "edge-dashboard", "to": "edge-api", "mode": "sync", "label": "HTTP"},
    {"from": "edge-vscode", "to": "edge-api", "mode": "sync", "label": "HTTP"},
    {"from": "edge-api", "to": "edge-worker-didier-vision", "mode": "sync", "label": "RPC"},
    {"from": "edge-api", "to": "edge-worker-didier-brain", "mode": "sync", "label": "RPC"},
    {"from": "edge-api", "to": "edge-worker-didier-audio", "mode": "async", "label": "queue"},
    {"from": "edge-api", "to": "edge-worker-didier-asr", "mode": "async", "label": "stream"},
    {"from": "edge-worker-didier-brain", "to": "edge-worker-didier-openclaw", "mode": "async", "label": "react"},
    {"from": "edge-worker-didier-openclaw", "to": "edge-didier-model", "mode": "sync", "label": "LLM"},
)

_TERMINAL_REPO_ROOT = Path(__file__).resolve().parents[2]
_TERMINAL_MAX_CHARS = 300
_TERMINAL_MAX_OUTPUT = 12000
_TERMINAL_BLOCKED_SNIPPETS = (
    "rm -rf /",
    "mkfs",
    "shutdown",
    "reboot",
    "poweroff",
)

async def _probe_worker_health(service: str, fallback_base: str) -> tuple[str, str]:
    try:
        response = await ipc_request(
            "GET",
            "/health",
            service=service,
            base_url=fallback_base,
            timeout=0.8,
        )
        if not response.is_success:
            return "offline", f"http {response.status_code}"
        payload = response.json()
        status = str(payload.get("status", "ok")).lower()
        detail = payload.get("detail") or payload.get("service") or payload.get("name") or "online"
        return status, str(detail)
    except Exception as exc:
        return "offline", str(exc)


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
    return {
        "timestamp": time.time(),
        "cpu": {"percent": 0.0, "temp_c": None, "per_core": []},
        "memory": {"total": 0, "used": 0, "percent": 0.0},
        "disk": {"root": {"available": False, "path": "/"}, "ssd": {"available": False, "path": "/mnt/didier_ssd"}},
        "npu": {"available": False, "device": False, "pcie": False, "utilization": None},
        "audio": {"available": False, "level_percent": 0, "listening": False},
        "workers": {},
        "source": "shared_state_v1",
    }


@router.get("/device-status")
async def device_status() -> dict[str, Any]:
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
            now = time.time()
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
    npu = await api_module.asyncio.to_thread(api_module._check_npu, npu_device, npu_pcie)
    tts = await api_module.asyncio.to_thread(
        api_module._check_tts, tts_model, tts_config, tts_voices
    )
    version = await api_module.asyncio.to_thread(api_module._read_version)

    return {
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
    timeout_s = float((payload or {}).get("timeout_seconds", 8))
    timeout_s = max(1.0, min(timeout_s, 15.0))
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
