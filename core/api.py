import asyncio
import base64
import json
import logging
import os
import signal
import subprocess
import time
import threading
from pathlib import Path
from typing import Any, Generator

import cv2
import psutil
import shutil
import soundfile as sf
import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.hardware_gatekeeper import get_hardware_gatekeeper
from core.logging import setup_logging
from core.network_discovery import get_network_discovery
from core.orchestrator import Orchestrator
from core.routers import ai_router, system_router, vision_router
from core.resource_arbitrator import get_resource_arbitrator
from core.shared_state import read_state as read_shared_state
from core.shared_state import update_hardware_profile
from core.shared_state import update_metrics as update_shared_metrics
from core.shared_state import update_worker_metrics
from core.status import read_status, update_status
from core.routers.actuators import router as actuators_router


app = FastAPI(title="Didier Orchestrator", version="2.0")
WEB_DIR = Path("web")
#app.mount("/static", StaticFiles(directory="web"), name="static")
INDEX_PATH = WEB_DIR / "index.html"
VERSION_PATH = Path("VERSION")
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.include_router(system_router)
app.include_router(vision_router)
app.include_router(ai_router)
app.include_router(actuators_router)
_orchestrator: Orchestrator | None = None
_camera_watchdog_task: asyncio.Task | None = None
_shared_state_task: asyncio.Task | None = None
_resource_arbitrator: Any | None = None
_orchestrator_bootstrap_task: asyncio.Task | None = None
_orchestrator_ready = False
_AUDIO_CACHE: dict[str, Any] = {"ts": 0.0, "level": None, "available": False}
_AUDIO_CACHE_LOCK = threading.Lock()
_NPU_CACHE: dict[str, Any] = {"ts": 0.0, "active": None, "util": None, "cores": {}}
_NPU_CACHE_LOCK = threading.Lock()
_VIDEO_LOCK = threading.Lock()
_HARDWARE_GATEKEEPER = get_hardware_gatekeeper()
try:
    import audioop  # type: ignore
except Exception:  # pragma: no cover
    audioop = None

_VISION_TAGS_PATH = Path("data/vision/tags.json")
_DOCKER_ROOT_CACHE: dict[str, Any] = {"path": None, "ts": 0.0}
_VERSION_CACHE: dict[str, Any] = {"git": None, "version": None, "loaded": False}
APP_STARTED_AT = time.time()
API_SHARED_STATE_INTERVAL_S = max(
    0.5, min(float(os.getenv("DIDIER_API_SHARED_STATE_INTERVAL_S", "1.0")), 5.0)
)
DEFAULT_HTTP_TIMEOUT_S = 2.0
DEFAULT_SUBPROCESS_TIMEOUT_S = 2.0
_REQUEST_THROTTLE_LOCK = threading.Lock()
_REQUEST_THROTTLE_LAST_TS: dict[tuple[str, str], float] = {}
_REQUEST_THROTTLE_LAST_CLEANUP = 0.0
_REQUEST_THROTTLE_TTL_S = 30.0
_REQUEST_THROTTLE_RULES_S: dict[str, float] = {
    "/vision/detections": 0.35,
    "/vision/detections-secondary": 0.80,
    "/vision/status-secondary": 0.50,
    "/vision/zones": 1.50,
    "/device-status": 0.75,
    "/ollama/models": 2.00,
}
_REQUEST_THROTTLE_FALLBACKS: dict[str, dict[str, Any]] = {
    "/vision/detections": {
        "detections": [],
        "frame": {"width": None, "height": None},
        "ts": 0.0,
        "source": "rate_limited",
    },
    "/vision/detections-secondary": {
        "detections": [],
        "frame": {"width": None, "height": None},
        "ts": 0.0,
        "stream_ts": 0.0,
        "status": {"state": "rate_limited"},
        "source": "rate_limited",
    },
    "/vision/status-secondary": {
        "status": "offline",
        "age_s": None,
        "ts": 0.0,
        "source": "rate_limited",
    },
    "/vision/zones": {
        "zones": [],
        "width": None,
        "height": None,
        "source": "rate_limited",
    },
}


def _http_timeout(seconds: float | int) -> float:
    return max(0.1, min(float(seconds), DEFAULT_HTTP_TIMEOUT_S))


def _client_ip(request: Request) -> str:
    if request.client and request.client.host:
        return str(request.client.host)
    forwarded = str(request.headers.get("x-forwarded-for", "")).strip()
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return "unknown"


def _request_throttle_check(request: Request) -> float | None:
    """
    Returns retry-after seconds when request should be throttled, else None.
    """
    path = request.url.path
    min_interval_s = _REQUEST_THROTTLE_RULES_S.get(path)
    if request.method != "GET" or min_interval_s is None:
        return None

    now = time.monotonic()
    client = _client_ip(request)
    key = (client, path)
    retry_after: float | None = None

    with _REQUEST_THROTTLE_LOCK:
        last_ts = _REQUEST_THROTTLE_LAST_TS.get(key, 0.0)
        delta = now - last_ts
        if delta < min_interval_s:
            retry_after = max(0.05, min_interval_s - delta)
        else:
            _REQUEST_THROTTLE_LAST_TS[key] = now

        global _REQUEST_THROTTLE_LAST_CLEANUP
        if (now - _REQUEST_THROTTLE_LAST_CLEANUP) >= 10.0:
            cutoff = now - _REQUEST_THROTTLE_TTL_S
            stale_keys = [
                stale_key
                for stale_key, stale_ts in _REQUEST_THROTTLE_LAST_TS.items()
                if stale_ts < cutoff
            ]
            for stale_key in stale_keys:
                _REQUEST_THROTTLE_LAST_TS.pop(stale_key, None)
            _REQUEST_THROTTLE_LAST_CLEANUP = now

    return retry_after


@app.middleware("http")
async def _request_throttle_middleware(request: Request, call_next):
    retry_after = _request_throttle_check(request)
    if retry_after is not None:
        fallback = _REQUEST_THROTTLE_FALLBACKS.get(request.url.path)
        if fallback is not None:
            response = JSONResponse(content=fallback, status_code=200)
        else:
            response = JSONResponse(content={"detail": "rate_limited"}, status_code=429)
        response.headers["Retry-After"] = f"{retry_after:.2f}"
        response.headers["X-Didier-RateLimit"] = "1"
        return response
    return await call_next(request)


def _run_subprocess(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    kwargs.setdefault("timeout", DEFAULT_SUBPROCESS_TIMEOUT_S)
    return subprocess.run(*args, **kwargs)


def _target_stream_interval(default_fps: int = 20) -> float:
    fps = max(1, min(int(default_fps or 20), 60))
    try:
        fps = get_resource_arbitrator().get_target_fps(default=fps)
    except Exception:
        pass
    fps = max(1, min(int(fps), 60))
    return max(1.0 / float(fps), 0.03)


def _get_docker_root() -> Path:
    # Compatibility shim: production runtime is now native systemd (no Docker root scan).
    return Path("/nonexistent")


def _read_docker_containers() -> list[dict[str, Any]]:
    # Compatibility shim for /docker/diagram legacy endpoint.
    return []


def _search_repo_files(query: str, limit: int = 40) -> list[dict[str, Any]]:
    query = query.strip().lower()
    if len(query) < 2:
        return []
    root = Path(".").resolve()
    ignored = {
        ".git",
        ".deps",
        "__pycache__",
        "venv",
        "node_modules",
        "models",
        "logs",
        "data",
        "ollama",
        "voices",
    }
    results: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in ignored and not d.startswith(".")]
        for filename in filenames:
            if filename.startswith("."):
                continue
            rel_path = str(Path(dirpath, filename).relative_to(root))
            if query not in filename.lower() and query not in rel_path.lower():
                continue
            try:
                size = (Path(dirpath) / filename).stat().st_size
            except Exception:
                size = None
            results.append({"path": rel_path, "size": size})
            if len(results) >= limit:
                return results
    return results


def _load_vision_tags() -> dict[str, str]:
    if not _VISION_TAGS_PATH.exists():
        return {}
    try:
        data = json.loads(_VISION_TAGS_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if v is not None}
    except Exception:
        return {}
    return {}


def _save_vision_tags(tags: dict[str, str]) -> None:
    _VISION_TAGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _VISION_TAGS_PATH.write_text(
        json.dumps(tags, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


async def _warmup_ollama() -> None:
    try:
        orchestrator = _require_orchestrator()
        config = orchestrator.config
        base_url = config.get("ollama.base_url", "http://localhost:11434")
        model = config.get("ollama.model", "")
        if not model:
            return
        payload: dict[str, Any] = {
            "model": model,
            "prompt": "Bonjour.",
            "stream": False,
            "options": {"num_predict": 1, "temperature": 0.2},
        }
        keep_alive = config.get("ollama.keep_alive", None)
        if keep_alive:
            payload["keep_alive"] = keep_alive
        import httpx

        async with httpx.AsyncClient(timeout=_http_timeout(90)) as client:
            await client.post(f"{base_url}/api/generate", json=payload)
    except Exception as exc:
        logging.getLogger("API").warning("Ollama warmup failed: %s", exc)


async def _shared_state_loop() -> None:
    while True:
        try:
            orchestrator = _require_orchestrator()
            npu_device = orchestrator.config.get("npu.device", "/dev/hailo0")
            npu_pcie = orchestrator.config.get("npu.pcie_address", "0001:01:00.0")
            ssd_mount = orchestrator.config.get("storage.ssd_mount", "/mnt/didier_ssd")
            host_root = "/host" if Path("/host").exists() else "/"
            host_ssd = f"{host_root}{ssd_mount}" if ssd_mount.startswith("/") else None
            ssd_path = _resolve_disk_path(
                ssd_mount,
                [
                    host_ssd,
                    f"{ssd_mount}/didier",
                    "/app",
                    "/app/logs",
                    "/root/.ollama",
                ],
            )
            cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
            if cpu_per_core:
                cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 1)
            else:
                cpu_percent = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            asr_status = _read_asr_status()
            hardware_profile: dict[str, Any] = {}
            try:
                discovery_cfg = orchestrator.config.get("hardware.discovery", {}) or {}
                discovery = get_network_discovery(config=discovery_cfg)
                discovery_result = await asyncio.to_thread(discovery.scan)
                profile_candidate = discovery_result.get("profile", {})
                if isinstance(profile_candidate, dict) and profile_candidate:
                    persisted = await asyncio.to_thread(
                        update_hardware_profile,
                        profile_candidate,
                        True,
                    )
                    if isinstance(persisted, dict):
                        hardware_profile = dict(persisted.get("profile", {}) or {})
            except Exception as exc:
                logging.getLogger("API").debug(
                    "hardware discovery skipped: %s",
                    exc,
                )
            state_snapshot = read_shared_state()
            workers_snapshot = state_snapshot.get("workers", {})
            if not hardware_profile:
                hardware_profile = dict(state_snapshot.get("hardware_profile", {}) or {})
            payload = {
                "timestamp": time.time(),
                "cpu": {
                    "percent": cpu_percent,
                    "temp_c": _read_cpu_temp_c(),
                    "per_core": cpu_per_core,
                },
                "memory": {
                    "total": mem.total,
                    "used": mem.used,
                    "percent": mem.percent,
                },
                "disk": {
                    "root": _disk_usage(host_root, "/"),
                    "ssd": _disk_usage(ssd_path, ssd_mount)
                    if ssd_path
                    else {"available": False, "path": ssd_mount},
                },
                "npu": _read_npu_usage(npu_device, npu_pcie),
                "audio": {
                    "available": True,
                    "level_percent": 0,
                    "listening": bool(asr_status.get("listening", False)),
                },
                "asr": {
                    "state": str(asr_status.get("state", "IDLE")),
                    "listening": bool(asr_status.get("listening", False)),
                    "last_heard_at": asr_status.get("last_heard_at"),
                    "last_asr_ms": asr_status.get("last_asr_ms"),
                },
                "workers": workers_snapshot,
                "hardware_profile": hardware_profile,
                "source": "shared_state_v1",
            }
            await asyncio.to_thread(update_shared_metrics, payload)
            await asyncio.to_thread(
                update_worker_metrics,
                "api",
                {
                    "status": "ok",
                    "service": "didier-api",
                    "uptime_s": round(time.time() - APP_STARTED_AT, 3),
                    "detail": "ready",
                },
            )
        except Exception as exc:
            await asyncio.to_thread(
                update_worker_metrics,
                "api",
                {
                    "status": "degraded",
                    "service": "didier-api",
                    "uptime_s": round(time.time() - APP_STARTED_AT, 3),
                    "detail": str(exc),
                },
            )
        await asyncio.sleep(API_SHARED_STATE_INTERVAL_S)


def _rms_pcm16(data: bytes) -> int:
    if not data:
        return 0
    try:
        samples = np.frombuffer(data, dtype=np.int16)
        if samples.size == 0:
            return 0
        return int(np.sqrt(np.mean(samples.astype(np.float32) ** 2)))
    except Exception:
        return 0


def _is_music_prompt(prompt: str) -> bool:
    lowered = prompt.lower()
    if "musique" not in lowered and "music" not in lowered:
        return False
    triggers = ("joue", "jouer", "lance", "mets", "play")
    return any(token in lowered for token in triggers)


def _resolve_expert_prompt(
    prompt: str, config: Any
) -> tuple[str, str | None, str | None, str | None]:
    experts = config.get("ollama.experts", {}) if config else {}
    if not isinstance(experts, dict):
        return prompt, None, None, None
    raw = prompt.strip()
    lowered = raw.lower()
    for name, entry in experts.items():
        if not isinstance(entry, dict):
            continue
        key = str(name).strip()
        if not key:
            continue
        key_lower = key.lower()
        if lowered.startswith(f"@{key_lower}"):
            cleaned = raw[len(key) + 1 :].lstrip(" :")
        elif lowered.startswith(f"{key_lower}:") or lowered.startswith(f"{key_lower} "):
            cleaned = raw[len(key) :].lstrip(" :")
        else:
            continue
        model = entry.get("model", None)
        system_prompt = entry.get("system_prompt", None)
        return cleaned if cleaned else raw, model, system_prompt, key
    return prompt, None, None, None


@app.on_event("startup")
async def startup_event() -> None:
    setup_logging()
    global _orchestrator, _orchestrator_bootstrap_task, _orchestrator_ready
    _orchestrator = Orchestrator()
    _orchestrator_ready = False
    _orchestrator_bootstrap_task = asyncio.create_task(_bootstrap_runtime())
    logging.getLogger("API").info("Didier API bootstrap scheduled.")


async def _bootstrap_runtime() -> None:
    global _camera_watchdog_task, _shared_state_task, _resource_arbitrator, _orchestrator_ready
    orchestrator = _orchestrator
    if orchestrator is None:
        return
    try:
        await orchestrator.start()
        _orchestrator_ready = True
        _resource_arbitrator = get_resource_arbitrator()
        _resource_arbitrator.start()
        _camera_watchdog_task = asyncio.create_task(_camera_watchdog())
        _shared_state_task = asyncio.create_task(_shared_state_loop())
        asyncio.create_task(_warmup_ollama())
        logging.getLogger("API").info("Didier API started.")
    except asyncio.CancelledError:
        raise
    except Exception:
        _orchestrator_ready = False
        logging.getLogger("API").exception("Didier API bootstrap failed.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global _orchestrator_bootstrap_task, _orchestrator_ready
    _orchestrator_ready = False
    if _orchestrator_bootstrap_task:
        _orchestrator_bootstrap_task.cancel()
        await asyncio.gather(_orchestrator_bootstrap_task, return_exceptions=True)
        _orchestrator_bootstrap_task = None
    if _orchestrator:
        await _orchestrator.stop()
    global _camera_watchdog_task, _shared_state_task, _resource_arbitrator
    if _camera_watchdog_task:
        _camera_watchdog_task.cancel()
        _camera_watchdog_task = None
    if _shared_state_task:
        _shared_state_task.cancel()
        _shared_state_task = None
    if _resource_arbitrator:
        _resource_arbitrator.stop()
        _resource_arbitrator = None


def _require_orchestrator() -> Orchestrator:
    if not _orchestrator or not _orchestrator_ready:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")
    return _orchestrator


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    if INDEX_PATH.exists():
        return HTMLResponse(
            content=INDEX_PATH.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-store, max-age=0"},
        )
    return HTMLResponse(
        content="<h1>Didier</h1><p>UI not found.</p>",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/ping")
async def ping() -> dict[str, Any]:
    return {"status": "ok", "name": "Didier"}


def _read_cpu_temp_c() -> float | None:
    temp_path = Path("/sys/class/thermal/thermal_zone0/temp")
    if not temp_path.exists():
        return None
    try:
        raw = temp_path.read_text().strip()
        return round(float(raw) / 1000.0, 1)
    except Exception:
        return None


def _format_go(value: int | float) -> str:
    gb = float(value) / (1024**3)
    if gb >= 10:
        return f"{int(round(gb))}GO"
    gb = round(gb, 1)
    if gb.is_integer():
        return f"{int(gb)}GO"
    return f"{gb}GO"


def _disk_usage(path: str, label_path: str | None = None) -> dict[str, Any]:
    try:
        usage = shutil.disk_usage(path)
    except Exception:
        return {"available": False, "path": label_path or path}
    total = usage.total
    used = usage.used
    percent = round((used / total) * 100, 1) if total else 0
    return {
        "available": True,
        "path": label_path or path,
        "total": total,
        "used": used,
        "free": usage.free,
        "percent": percent,
        "label": f"{_format_go(used)}/{_format_go(total)}",
    }


def _resolve_disk_path(primary: str | None, fallbacks: list[str]) -> str | None:
    candidates: list[str] = []
    if primary:
        candidates.append(primary)
    for candidate in fallbacks:
        if candidate:
            candidates.append(candidate)
    for candidate in candidates:
        try:
            if Path(candidate).exists():
                return candidate
        except Exception:
            continue
    return primary


def _read_npu_usage(device_path: str | None, pcie_address: str | None) -> dict[str, Any]:
    device_ok = Path(device_path).exists() if device_path else False
    pcie_path = Path(f"/sys/bus/pci/devices/{pcie_address}") if pcie_address else None
    pcie_ok = pcie_path.exists() if pcie_path else False
    utilization = None
    active = False
    cores: list[dict[str, Any]] = []

    if device_ok and pcie_ok and pcie_path:
        hailo_dir = pcie_path / "hailo_chardev"
        runtime_nodes: list[tuple[str, Path, Path | None]] = []
        if hailo_dir.exists():
            for child in sorted(hailo_dir.iterdir(), key=lambda path: path.name):
                active_path = child / "power" / "runtime_active_time"
                status_path = child / "power" / "runtime_status"
                if active_path.exists():
                    runtime_nodes.append(
                        (
                            child.name,
                            active_path,
                            status_path if status_path.exists() else None,
                        )
                    )

        now = time.time()
        with _NPU_CACHE_LOCK:
            core_cache = _NPU_CACHE.setdefault("cores", {})
            if not isinstance(core_cache, dict):
                core_cache = {}
                _NPU_CACHE["cores"] = core_cache

            seen_core_ids: set[str] = set()
            for core_id, active_path, status_path in runtime_nodes:
                seen_core_ids.add(core_id)
                runtime_status = None
                if status_path is not None:
                    try:
                        runtime_status = status_path.read_text().strip().lower()
                    except Exception:
                        runtime_status = None

                active_value = None
                try:
                    active_value = int(active_path.read_text().strip())
                except Exception:
                    active_value = None

                prev = core_cache.get(core_id, {})
                prev_active = prev.get("active")
                prev_ts = prev.get("ts")
                prev_util = prev.get("utilization")
                util_core = None
                if active_value is not None:
                    if prev_active is not None and prev_ts:
                        delta_active = max(0, int(active_value) - int(prev_active))
                        delta_wall = max(0.001, now - float(prev_ts))
                        # runtime_active_time is usually expressed in microseconds.
                        active_seconds = delta_active / 1_000_000
                        util_core = int(
                            max(0, min(100, (active_seconds / delta_wall) * 100))
                        )
                    elif isinstance(prev_util, (int, float)):
                        util_core = int(max(0, min(100, float(prev_util))))

                    core_cache[core_id] = {
                        "active": int(active_value),
                        "ts": now,
                        "utilization": util_core,
                    }
                elif isinstance(prev_util, (int, float)):
                    util_core = int(max(0, min(100, float(prev_util))))

                if isinstance(util_core, (int, float)) and float(util_core) > 0.0:
                    active = True
                if runtime_status in {"active", "resuming"}:
                    active = True

                cores.append(
                    {
                        "id": core_id,
                        "utilization": util_core,
                        "runtime_status": runtime_status,
                    }
                )

            stale_ids = [key for key in core_cache.keys() if key not in seen_core_ids]
            for key in stale_ids:
                core_cache.pop(key, None)

            measured_utils = [
                float(item["utilization"])
                for item in cores
                if isinstance(item.get("utilization"), (int, float))
            ]
            if measured_utils:
                utilization = int(
                    max(0, min(100, round(sum(measured_utils) / len(measured_utils))))
                )
                _NPU_CACHE["util"] = utilization
            else:
                cached_util = _NPU_CACHE.get("util")
                if isinstance(cached_util, (int, float)):
                    utilization = int(max(0, min(100, float(cached_util))))

            _NPU_CACHE["ts"] = now
            _NPU_CACHE["active"] = bool(active)

    if isinstance(utilization, (int, float)) and float(utilization) > 0.0:
        active = True

    return {
        "available": device_ok and pcie_ok,
        "utilization": utilization,
        "active": bool(active),
        "core_count": len(cores),
        "cores": cores,
    }


def _read_asr_status() -> dict[str, Any]:
    status = read_status()
    status.setdefault("listening", False)
    status.setdefault("thinking", False)
    status.setdefault("speaking", False)
    status.setdefault("state", "IDLE")
    return status


def _read_mic_level(
    alsa_device: str, sample_rate: int, channels: int = 1, cooldown: float = 1.5
) -> dict[str, Any]:
    if not alsa_device:
        return {"available": False, "level_percent": None, "listening": False}
    if shutil.which("arecord") is None:
        return {"available": False, "level_percent": None, "listening": False}
    status = _read_asr_status()
    if status.get("listening"):
        with _AUDIO_CACHE_LOCK:
            cached_level = _AUDIO_CACHE["level"]
        return {
            "available": True,
            "level_percent": cached_level,
            "listening": True,
        }
    now = time.time()
    with _AUDIO_CACHE_LOCK:
        if now - _AUDIO_CACHE["ts"] < cooldown and _AUDIO_CACHE["level"] is not None:
            return {
                "available": bool(_AUDIO_CACHE["available"]),
                "level_percent": _AUDIO_CACHE["level"],
                "cached": True,
                "listening": False,
            }

    cmd = [
        "arecord",
        "-q",
        "-D",
        alsa_device,
        "-f",
        "S16_LE",
        "-r",
        str(sample_rate),
        "-c",
        str(channels),
        "-d",
        "1",
        "-t",
        "raw",
    ]
    try:
        result = _run_subprocess(
            cmd,
            capture_output=True,
            check=False,
            timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
        )
        data = result.stdout or b""
        if not data:
            level_percent = 0
        else:
            if audioop:
                rms = audioop.rms(data, 2)
            else:
                rms = _rms_pcm16(data)
            level_percent = int(min(100, max(0, (rms / 32768) * 100)))
        with _AUDIO_CACHE_LOCK:
            _AUDIO_CACHE["ts"] = time.time()
            _AUDIO_CACHE["level"] = level_percent
            _AUDIO_CACHE["available"] = True
        return {"available": True, "level_percent": level_percent, "listening": False}
    except Exception as exc:
        return {
            "available": False,
            "level_percent": None,
            "listening": False,
            "error": str(exc),
        }


def _read_version() -> dict[str, Any]:
    if _VERSION_CACHE["loaded"]:
        return {
            "git": _VERSION_CACHE["git"],
            "version": _VERSION_CACHE["version"],
        }

    git_hash = None
    try:
        result = _run_subprocess(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_hash = result.stdout.strip()
    except Exception:
        git_hash = None

    file_version = None
    if VERSION_PATH.exists():
        file_version = VERSION_PATH.read_text(encoding="utf-8").strip()

    _VERSION_CACHE["git"] = git_hash
    _VERSION_CACHE["version"] = file_version
    _VERSION_CACHE["loaded"] = True
    return {"git": git_hash, "version": file_version}


async def _resolve_ollama_model(
    base_url: str, preferred: str, fallback: str | None = None
) -> str:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=_http_timeout(10)) as client:
            response = await client.get(f"{base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
        models = [
            m.get("name") or m.get("model")
            for m in (data.get("models") or [])
            if (m.get("name") or m.get("model"))
        ]
        if preferred in models:
            return preferred
        if fallback and fallback in models:
            return fallback
        if models:
            return models[0]
    except Exception:
        pass
    return preferred


def _check_soundboks_sink(sink_name: str) -> dict[str, Any]:
    try:
        def _parse_sink_names(raw_output: str) -> list[str]:
            names: list[str] = []
            for raw in raw_output.splitlines():
                line = raw.strip()
                if not line:
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    names.append(parts[1].strip())
                    continue
                fallback = line.split()
                if len(fallback) >= 2:
                    names.append(fallback[1].strip())
            return names

        result = _run_subprocess(
            ["pactl", "list", "short", "sinks"],
            capture_output=True,
            text=True,
            check=True,
        )
        sink_names = _parse_sink_names(result.stdout or "")

        mac_token = ""
        if sink_name.startswith("bluez_output."):
            mac_token = sink_name[len("bluez_output.") :].split(".", 1)[0]
        exact_match = bool(sink_name) and sink_name in sink_names
        fuzzy_match = None
        if mac_token:
            for name in sink_names:
                if name.startswith("bluez_output.") and mac_token in name:
                    fuzzy_match = name
                    break

        default_sink = None
        info = _run_subprocess(
            ["pactl", "info"], capture_output=True, text=True, check=False
        )
        for line in (info.stdout or "").splitlines():
            if line.startswith("Default Sink:"):
                default_sink = line.split(":", 1)[1].strip() or None
                break

        available = exact_match or bool(fuzzy_match)
        matched_sink = sink_name if exact_match else fuzzy_match

        self_healed = False
        if not available and mac_token:
            card_name = f"bluez_card.{mac_token}"
            _run_subprocess(
                ["pactl", "set-card-profile", card_name, "a2dp-sink"],
                capture_output=True,
                text=True,
                check=False,
            )
            retry = _run_subprocess(
                ["pactl", "list", "short", "sinks"],
                capture_output=True,
                text=True,
                check=False,
            )
            retry_names = _parse_sink_names(retry.stdout or "")
            for name in retry_names:
                if name == sink_name or (mac_token and mac_token in name):
                    available = True
                    matched_sink = name
                    self_healed = True
                    break

        if not available and default_sink:
            if sink_name and default_sink == sink_name:
                available = True
                matched_sink = default_sink
            elif mac_token and mac_token in default_sink:
                available = True
                matched_sink = default_sink
        if available and matched_sink and default_sink != matched_sink:
            _run_subprocess(
                ["pactl", "set-default-sink", matched_sink],
                capture_output=True,
                text=True,
                check=False,
            )
        return {
            "available": available,
            "sink": sink_name,
            "matched_sink": matched_sink,
            "default_sink": default_sink,
            "self_healed": self_healed,
        }
    except Exception as exc:
        return {"available": False, "sink": sink_name, "error": str(exc)}


def _camera_holders(device: str | None) -> dict[str, Any]:
    if not device:
        return {"output": "Aucun périphérique configuré"}
    if shutil.which("fuser") is None:
        return {"output": "fuser indisponible"}
    verbose = _run_subprocess(
        ["fuser", "-v", device], capture_output=True, text=True, check=False
    )
    plain = _run_subprocess(
        ["fuser", device], capture_output=True, text=True, check=False
    )
    output_verbose = ((verbose.stdout or "") + (verbose.stderr or "")).strip()
    output_plain = ((plain.stdout or "") + (plain.stderr or "")).strip()
    pids = []
    for token in output_plain.replace(":", " ").split():
        if token.isdigit():
            pids.append(token)
    pids = sorted(set(pids))
    if not pids:
        # Fallback: scan /proc for open fds
        for pid_dir in Path("/proc").iterdir():
            if not pid_dir.name.isdigit():
                continue
            fd_dir = pid_dir / "fd"
            if not fd_dir.exists():
                continue
            try:
                for fd in fd_dir.iterdir():
                    try:
                        target = os.readlink(fd)
                    except OSError:
                        continue
                    if target == device:
                        pids.append(pid_dir.name)
                        break
            except PermissionError:
                continue
        pids = sorted(set(pids))
    details = []
    if pids:
        ps = _run_subprocess(
            ["ps", "-o", "pid,user,comm", "-p", ",".join(pids)],
            capture_output=True,
            text=True,
            check=False,
        )
        ps_output = (ps.stdout or "").strip()
        details.append(f"PIDs : {', '.join(pids)}")
        if ps_output:
            details.append(ps_output)
            if "uvicorn" in ps_output:
                details.append(
                    "Note : le flux MJPEG de Didier garde la caméra ouverte tant que la page est ouverte."
                )
    if output_verbose:
        details.append("fuser -v :")
        details.append(output_verbose)
    if not details:
        details.append(
            "Aucun PID détecté. Peut-être un accès noyau ou un processus root hors conteneur."
        )
    return {"output": "\n".join(details), "pids": pids}


def _camera_reconnect(device: str | None) -> dict[str, Any]:
    pids: list[int] = []
    if device and shutil.which("fuser"):
        result = _run_subprocess(["fuser", device], capture_output=True, text=True, check=False)
        tokens = (result.stdout or "").replace(":", " ").split()
        own_pids = {os.getpid(), os.getppid()}
        for token in tokens:
            if token.isdigit():
                pid = int(token)
                if pid not in own_pids:
                    pids.append(pid)
    # Kill known camera processes as a fallback
    for name in ["libcamera-vid", "libcamera-still", "libcamera-hello", "rpicam-vid", "rpicam-still", "mjpg_streamer", "ffmpeg", "gst-launch-1.0"]:
        _run_subprocess(["pkill", "-9", "-f", name], check=False)
    if pids:
        for pid in pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
        time.sleep(0.2)
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                pass
    if shutil.which("modprobe"):
        modules_dir = Path("/lib/modules")
        if modules_dir.exists():
            _run_subprocess(["modprobe", "-r", "uvcvideo"], check=False)
            _run_subprocess(["modprobe", "uvcvideo"], check=False)
    return {"status": "relance tentée"}


def _camera_force_format(device: str | None, width: int | None, height: int | None, fourcc: str | None) -> dict[str, Any]:
    if not device:
        return {"status": "aucun périphérique configuré"}
    if shutil.which("v4l2-ctl") is None:
        return {"status": "v4l2-ctl absent"}
    width = width or 640
    height = height or 480
    fourcc = fourcc or "YUYV"
    cmd = [
        "v4l2-ctl",
        "-d",
        device,
        f"--set-fmt-video=width={width},height={height},pixelformat={fourcc}",
    ]
    result = _run_subprocess(cmd, capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    return {"status": "format tenté", "output": output.strip()}


def _check_camera(index: int, device: str | None) -> dict[str, Any]:
    lease = _HARDWARE_GATEKEEPER.acquire("camera", timeout_s=0.2, blocking=False)
    if lease is None:
        return {
            "device": device or f"index:{index}",
            "opened": False,
            "busy": True,
            "error": "camera_gate_locked",
        }
    try:
        cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
        opened = cap.isOpened()
        ret = False
        if opened:
            ret, _ = cap.read()
        cap.release()
        return {
            "device": device or f"index:{index}",
            "opened": opened,
            "frame": ret,
        }
    except Exception as exc:
        return {"device": device or f"index:{index}", "opened": False, "error": str(exc)}
    finally:
        lease.release()


def _check_camera_mic() -> dict[str, Any]:
    cards_path = Path("/proc/asound/cards")
    if not cards_path.exists():
        return {"available": False, "error": "no /proc/asound/cards"}
    content = cards_path.read_text(encoding="utf-8")
    available = "USB" in content or "Camera" in content or "PS3" in content
    return {"available": available}


def _check_camera_usb(vendor: str | None, product: str | None) -> dict[str, Any]:
    if not vendor or not product:
        return {"present": False, "error": "usb id not configured"}
    base = Path("/sys/bus/usb/devices")
    if not base.exists():
        return {"present": False, "error": "no /sys/bus/usb/devices"}
    for dev in base.iterdir():
        v = dev / "idVendor"
        p = dev / "idProduct"
        if not v.exists() or not p.exists():
            continue
        if v.read_text().strip().lower() == vendor.lower() and p.read_text().strip().lower() == product.lower():
            return {"present": True, "path": str(dev)}
    return {"present": False}


def _check_npu(device_path: str | None, pcie_address: str | None) -> dict[str, Any]:
    device_ok = Path(device_path).exists() if device_path else False
    pcie_ok = Path(f"/sys/bus/pci/devices/{pcie_address}").exists() if pcie_address else False
    return {"device": device_ok, "pcie": pcie_ok}


def _check_tts(
    model_path: str | None, config_path: str | None, voices_path: str | None = None
) -> dict[str, Any]:
    model_ok = Path(model_path).exists() if model_path else False
    config_ok = Path(config_path).exists() if config_path else False
    voices_ok = Path(voices_path).exists() if voices_path else False
    paplay_ok = shutil.which("paplay") is not None
    return {
        "model": model_ok,
        "config": config_ok or voices_ok,
        "paplay": paplay_ok,
    }


def _normalize_zones(
    zones: Any, width: int | None, height: int | None
) -> list[dict[str, Any]]:
    if not zones:
        return []
    normalized: list[dict[str, Any]] = []
    for idx, zone in enumerate(zones):
        name = f"zone-{idx + 1}"
        color = None
        if isinstance(zone, dict):
            name = zone.get("name", name)
            color = zone.get("color")
            x, y, w, h = (
                zone.get("x"),
                zone.get("y"),
                zone.get("w"),
                zone.get("h"),
            )
        elif isinstance(zone, (list, tuple)) and len(zone) >= 4:
            x, y, w, h = zone[:4]
        else:
            continue
        try:
            x = float(x)
            y = float(y)
            w = float(w)
            h = float(h)
        except Exception:
            continue
        if max(x, y, w, h) > 1.0:
            if width and height:
                x = x / float(width)
                y = y / float(height)
                w = w / float(width)
                h = h / float(height)
            else:
                continue
        x = max(0.0, min(1.0, x))
        y = max(0.0, min(1.0, y))
        w = max(0.0, min(1.0, w))
        h = max(0.0, min(1.0, h))
        normalized.append(
            {
                "name": name,
                "color": color,
                "x": x,
                "y": y,
                "w": w,
                "h": h,
            }
        )
    return normalized


async def _camera_watchdog() -> None:
    while True:
        await asyncio.sleep(10)
        if _orchestrator is None:
            continue
        cfg = _orchestrator.config
        if not cfg.get("vision.watchdog_enabled", False):
            continue
        camera_index = int(cfg.get("vision.camera_index", 0))
        camera_device = cfg.get("vision.camera_device", None)
        result = _check_camera(camera_index, camera_device)
        if bool(result.get("busy", False)) or str(result.get("error", "")) == "camera_gate_locked":
            # Another Didier component currently owns camera access; this is expected.
            continue
        if not result.get("opened") or not result.get("frame"):
            _camera_reconnect(camera_device)


def _apply_camera_settings(
    cap: cv2.VideoCapture, width: int | None, height: int | None, fps: int | None, fourcc: str | None
) -> None:
    if fourcc:
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*fourcc))
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps:
        cap.set(cv2.CAP_PROP_FPS, fps)
    try:
        # Minimize buffered frames to keep USB PS3 stream responsive.
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass


def _open_camera(
    device: str | None,
    index: int,
    width: int | None,
    height: int | None,
    fps: int | None,
    fourcc: str | None,
    kill_on_open: bool = False,
) -> cv2.VideoCapture:
    lease = _HARDWARE_GATEKEEPER.acquire("camera", timeout_s=0.4, blocking=False)
    if lease is None:
        raise RuntimeError("camera_gate_locked")
    try:
        if kill_on_open and device and shutil.which("fuser"):
            try:
                result = _run_subprocess(
                    ["fuser", device], capture_output=True, text=True, check=False
                )
                own_pids = {os.getpid(), os.getppid()}
                tokens = (result.stdout or "").replace(":", " ").split()
                for token in tokens:
                    if not token.isdigit():
                        continue
                    pid = int(token)
                    if pid in own_pids:
                        continue
                    try:
                        os.kill(pid, signal.SIGTERM)
                    except Exception:
                        pass
            except Exception:
                pass
        attempts: list[tuple[str | int, int | None]] = []
        if device:
            attempts.append((device, cv2.CAP_V4L2))
            attempts.append((device, None))
        attempts.append((index, cv2.CAP_V4L2))
        attempts.append((index, None))

        for source, api_pref in attempts:
            cap = (
                cv2.VideoCapture(source, api_pref)
                if api_pref is not None
                else cv2.VideoCapture(source)
            )
            if not cap.isOpened():
                cap.release()
                continue
            _apply_camera_settings(cap, width, height, fps, fourcc)
            for _ in range(2):
                try:
                    cap.grab()
                except Exception:
                    break
            return cap

        fallback = cv2.VideoCapture(index, cv2.CAP_V4L2)
        if fallback.isOpened():
            _apply_camera_settings(fallback, width, height, fps, fourcc)
        return fallback
    finally:
        lease.release()


def _mjpeg_generator(
    camera_device: str | None,
    camera_index: int,
    width: int | None,
    height: int | None,
    fps: int | None,
    fourcc: str | None,
    kill_on_open: bool,
) -> Generator[bytes, None, None]:
    if not _VIDEO_LOCK.acquire(blocking=False):
        raise RuntimeError("Camera busy")
    camera_lease = _HARDWARE_GATEKEEPER.acquire("camera", timeout_s=0.4, blocking=False)
    if camera_lease is None:
        _VIDEO_LOCK.release()
        raise RuntimeError("camera_gate_locked")
    cap: cv2.VideoCapture | None = None
    try:
        cap = _open_camera(
            camera_device, camera_index, width, height, fps, fourcc, kill_on_open
        )
        if not cap.isOpened():
            cap.release()
            cap = None
            if camera_device:
                yield from _mjpeg_generator_v4l2(
                    camera_device, width, height, fps, fourcc
                )
                return
            raise RuntimeError("Unable to open camera")
        failures = 0
        reopen_attempts = 0
        for _ in range(5):
            cap.read()
        while True:
            ret, frame = cap.read()
            if not ret:
                failures += 1
                if failures >= 30:
                    cap.release()
                    time.sleep(0.2)
                    cap = _open_camera(
                        camera_device,
                        camera_index,
                        width,
                        height,
                        fps,
                        fourcc,
                        kill_on_open,
                    )
                    reopen_attempts += 1
                    failures = 0
                    if reopen_attempts >= 2 and camera_device:
                        cap.release()
                        yield from _mjpeg_generator_v4l2(
                            camera_device, width, height, fps, fourcc
                        )
                        return
                time.sleep(0.05)
                continue
            failures = 0
            ok, buffer = cv2.imencode(".jpg", frame)
            if not ok:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
            )
            time.sleep(_target_stream_interval(default_fps=int(fps or 20)))
    finally:
        if cap is not None:
            cap.release()
        camera_lease.release()
        _VIDEO_LOCK.release()


def _mjpeg_generator_from_vision(vision: Any) -> Generator[bytes, None, None]:
    last_frame = None
    while True:
        frame = None
        try:
            frame = vision.get_latest_jpeg()
        except Exception:
            frame = None
        if frame:
            if frame is not last_frame:
                last_frame = frame
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        time.sleep(_target_stream_interval(default_fps=20))


def _mjpeg_generator_v4l2(
    camera_device: str,
    width: int | None,
    height: int | None,
    fps: int | None,
    fourcc: str | None,
) -> Generator[bytes, None, None]:
    if shutil.which("v4l2-ctl") is None:
        raise RuntimeError("v4l2-ctl absent")
    width = int(width or 640)
    height = int(height or 480)
    fourcc = (fourcc or "YUYV").upper()
    fmt_cmd = [
        "v4l2-ctl",
        "-d",
        camera_device,
        f"--set-fmt-video=width={width},height={height},pixelformat={fourcc}",
    ]
    _run_subprocess(fmt_cmd, check=False)
    if fps:
        _run_subprocess(
            ["v4l2-ctl", "-d", camera_device, f"--set-parm={int(fps)}"],
            check=False,
        )
    cmd = [
        "v4l2-ctl",
        "-d",
        camera_device,
        "--stream-mmap",
        "--stream-count=100000",
        "--stream-to=-",
    ]
    loop = asyncio.new_event_loop()
    try:
        proc = loop.run_until_complete(
            asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                ),
                timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
            )
        )
    except Exception:
        loop.close()
        raise
    if not proc.stdout:
        try:
            proc.terminate()
        except Exception:
            pass
        loop.close()
        raise RuntimeError("v4l2-ctl stdout unavailable")
    bytes_per_pixel = 2
    if fourcc in {"GRBG", "RGGB", "GBRG", "BGGR"}:
        bytes_per_pixel = 1
    frame_size = width * height * bytes_per_pixel

    def read_exact(size: int) -> bytes | None:
        data = b""
        while len(data) < size:
            try:
                chunk = loop.run_until_complete(
                    asyncio.wait_for(
                        proc.stdout.read(size - len(data)),
                        timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
                    )
                )
            except asyncio.TimeoutError:
                return None
            if not chunk:
                return None
            data += chunk
        return data

    try:
        import numpy as np

        while True:
            raw = read_exact(frame_size)
            if raw is None:
                break
            if bytes_per_pixel == 2:
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 2))
                if fourcc == "UYVY":
                    bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_UYVY)
                else:
                    bgr = cv2.cvtColor(frame, cv2.COLOR_YUV2BGR_YUYV)
            else:
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width))
                bgr = cv2.cvtColor(frame, cv2.COLOR_BayerGR2BGR)
            ok, buffer = cv2.imencode(".jpg", bgr)
            if not ok:
                continue
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + buffer.tobytes() + b"\r\n"
            )
            time.sleep(_target_stream_interval(default_fps=int(fps or 20)))
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            loop.run_until_complete(
                asyncio.wait_for(proc.wait(), timeout=DEFAULT_SUBPROCESS_TIMEOUT_S)
            )
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
            try:
                loop.run_until_complete(proc.wait())
            except Exception:
                pass
        loop.close()


class RemoteMjpegStream:
    def __init__(self, input_url: str, fps: int = 15) -> None:
        self._input_url = input_url
        self._fps = fps
        self._proc: asyncio.subprocess.Process | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._last_jpeg: bytes | None = None
        self._last_ts: float = 0.0
        self._last_error: str | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        if shutil.which("ffmpeg") is None:
            self._last_error = "ffmpeg not installed"
            return
        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-fflags",
            "nobuffer",
            "-flags",
            "low_delay",
            "-i",
            self._input_url,
            "-an",
            "-vf",
            f"fps={self._fps}",
            "-f",
            "image2pipe",
            "-vcodec",
            "mjpeg",
            "-",
        ]
        loop: asyncio.AbstractEventLoop | None = None
        try:
            loop = asyncio.new_event_loop()
            self._proc = loop.run_until_complete(
                asyncio.wait_for(
                    asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    ),
                    timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
                )
            )
        except Exception as exc:
            self._last_error = str(exc)
            try:
                if loop is not None:
                    loop.close()
            except Exception:
                pass
            return
        buffer = b""
        try:
            while not self._stop.is_set():
                if not self._proc or not self._proc.stdout:
                    break
                try:
                    chunk = loop.run_until_complete(
                        asyncio.wait_for(
                            self._proc.stdout.read(4096),
                            timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
                        )
                    )
                except asyncio.TimeoutError:
                    continue
                if not chunk:
                    break
                buffer += chunk
                while True:
                    start = buffer.find(b"\xff\xd8")
                    if start == -1:
                        break
                    end = buffer.find(b"\xff\xd9", start + 2)
                    if end == -1:
                        break
                    frame = buffer[start : end + 2]
                    buffer = buffer[end + 2 :]
                    with self._lock:
                        self._last_jpeg = frame
                        self._last_ts = time.time()
        finally:
            if self._proc:
                try:
                    self._proc.terminate()
                except Exception:
                    pass
                try:
                    loop.run_until_complete(
                        asyncio.wait_for(
                            self._proc.wait(),
                            timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
                        )
                    )
                except Exception:
                    try:
                        self._proc.kill()
                    except Exception:
                        pass
                    try:
                        loop.run_until_complete(self._proc.wait())
                    except Exception:
                        pass
                self._proc = None
            try:
                loop.close()
            except Exception:
                pass

    def get_last(self) -> tuple[bytes | None, float]:
        with self._lock:
            return self._last_jpeg, self._last_ts


_REMOTE_STREAM: RemoteMjpegStream | None = None
_REMOTE_STREAM_LOCK = threading.Lock()


def _get_remote_stream(input_url: str, fps: int = 15) -> RemoteMjpegStream:
    global _REMOTE_STREAM
    with _REMOTE_STREAM_LOCK:
        if _REMOTE_STREAM is None or _REMOTE_STREAM._input_url != input_url:
            _REMOTE_STREAM = RemoteMjpegStream(input_url, fps=fps)
        _REMOTE_STREAM.start()
        return _REMOTE_STREAM


def _remote_mjpeg_generator(stream: RemoteMjpegStream) -> Generator[bytes, None, None]:
    last_sent = None
    target_fps = max(int(getattr(stream, "_fps", 15) or 15), 1)
    while True:
        frame, _ts = stream.get_last()
        if frame and frame is not last_sent:
            last_sent = frame
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            )
        time.sleep(_target_stream_interval(default_fps=target_fps))
