import time
from pathlib import Path
from typing import Any

import psutil
from fastapi import APIRouter

router = APIRouter()


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
