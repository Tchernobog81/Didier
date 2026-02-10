import time
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "name": "Didier"}


@router.get("/version")
async def version() -> dict[str, Any]:
    from core import api as api_module

    return api_module._read_version()


@router.get("/metrics")
async def metrics() -> dict[str, Any]:
    from core import api as api_module

    cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    if cpu_per_core:
        cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 1)
    else:
        cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    orchestrator = api_module._require_orchestrator()
    npu_device = orchestrator.config.get("npu.device", "/dev/hailo0")
    npu_pcie = orchestrator.config.get("npu.pcie_address", "0001:01:00.0")
    didier_model = orchestrator.config.get("ollama.model", None)
    clawbot_model = orchestrator.config.get("clawbot.model", None)
    ssd_mount = orchestrator.config.get("storage.ssd_mount", "/mnt/didier_ssd")
    host_root = "/host" if Path("/host").exists() else "/"
    host_ssd = f"{host_root}{ssd_mount}" if ssd_mount.startswith("/") else None
    ssd_path = api_module._resolve_disk_path(
        ssd_mount,
        [
            host_ssd,
            f"{ssd_mount}/didier",
            "/app",
            "/app/logs",
            "/root/.ollama",
        ],
    )
    disk_root = api_module._disk_usage(host_root, "/")
    disk_ssd = (
        api_module._disk_usage(ssd_path, ssd_mount)
        if ssd_path
        else {"available": False, "path": ssd_mount}
    )
    # Bypass micro capture by default to avoid costly arecord subprocess calls.
    audio = {"available": True, "level_percent": 0, "listening": False}
    return {
        "timestamp": time.time(),
        "cpu": {
            "percent": cpu_percent,
            "temp_c": api_module._read_cpu_temp_c(),
            "per_core": cpu_per_core,
        },
        "memory": {
            "total": mem.total,
            "used": mem.used,
            "percent": mem.percent,
        },
        "disk": {
            "root": disk_root,
            "ssd": disk_ssd,
            "percent": disk_root.get("percent", 0),
        },
        "npu": api_module._read_npu_usage(npu_device, npu_pcie),
        "audio": audio,
    }


@router.get("/device-status")
async def device_status() -> dict[str, Any]:
    from core import api as api_module

    orchestrator = api_module._require_orchestrator()
    camera_index = int(orchestrator.config.get("vision.camera_index", 0))
    camera_device = orchestrator.config.get("vision.camera_device", None)
    vendor = orchestrator.config.get("vision.usb_id_vendor", None)
    product = orchestrator.config.get("vision.usb_id_product", None)
    sink = orchestrator.config.get("bluetooth.sink_name", "")
    tts_model = orchestrator.config.get("tts.model_path", None)
    tts_config = orchestrator.config.get("tts.config_path", None)
    npu_device = orchestrator.config.get("npu.device", "/dev/hailo0")
    npu_pcie = orchestrator.config.get("npu.pcie_address", "0001:01:00.0")
    didier_model = orchestrator.config.get("ollama.model", None)
    clawbot_model = orchestrator.config.get("clawbot.model", None)
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
    tts = await api_module.asyncio.to_thread(api_module._check_tts, tts_model, tts_config)
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
            "clawbot": clawbot_model,
        },
    }


@router.get("/docker/diagram")
async def docker_diagram() -> dict[str, Any]:
    from core import api as api_module

    try:
        containers = api_module._read_docker_containers()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Docker unavailable: {exc}")
    return {"ts": time.time(), "containers": containers}


@router.get("/files/search")
async def files_search(q: str = "") -> dict[str, Any]:
    from core import api as api_module

    query = str(q or "").strip()
    if len(query) < 2:
        return {"results": []}
    results = await api_module.asyncio.to_thread(api_module._search_repo_files, query)
    return {"results": results}


@router.get("/camera/holders")
async def camera_holders() -> dict[str, Any]:
    from core import api as api_module

    orchestrator = api_module._require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    return await api_module.asyncio.to_thread(api_module._camera_holders, camera_device)


@router.post("/camera/reconnect")
async def camera_reconnect() -> dict[str, Any]:
    from core import api as api_module

    orchestrator = api_module._require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    return await api_module.asyncio.to_thread(api_module._camera_reconnect, camera_device)


@router.post("/camera/force-format")
async def camera_force_format() -> dict[str, Any]:
    from core import api as api_module

    orchestrator = api_module._require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    width = orchestrator.config.get("vision.width", None)
    height = orchestrator.config.get("vision.height", None)
    fourcc = orchestrator.config.get("vision.fourcc", None)
    return await api_module.asyncio.to_thread(
        api_module._camera_force_format, camera_device, width, height, fourcc
    )
