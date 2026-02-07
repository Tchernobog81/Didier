import asyncio
import audioop
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
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from core.logging import setup_logging
from core.memory import MemoryStore
from core.orchestrator import Orchestrator
from core.status import read_status, update_status


app = FastAPI(title="Didier Orchestrator", version="2.0")
WEB_DIR = Path("web")
INDEX_PATH = WEB_DIR / "index.html"
VERSION_PATH = Path("VERSION")
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
_orchestrator: Orchestrator | None = None
_camera_watchdog_task: asyncio.Task | None = None
_AUDIO_CACHE: dict[str, Any] = {"ts": 0.0, "level": None, "available": False}
_AUDIO_CACHE_LOCK = threading.Lock()
_NPU_CACHE: dict[str, Any] = {"ts": 0.0, "active": None, "util": None}
_NPU_CACHE_LOCK = threading.Lock()
_VIDEO_LOCK = threading.Lock()


def _is_music_prompt(prompt: str) -> bool:
    lowered = prompt.lower()
    if "musique" not in lowered and "music" not in lowered:
        return False
    triggers = ("joue", "jouer", "lance", "mets", "play")
    return any(token in lowered for token in triggers)


@app.on_event("startup")
async def startup_event() -> None:
    setup_logging()
    global _orchestrator
    _orchestrator = Orchestrator()
    await _orchestrator.start()
    global _camera_watchdog_task
    _camera_watchdog_task = asyncio.create_task(_camera_watchdog())
    logging.getLogger("API").info("Didier API started.")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    if _orchestrator:
        await _orchestrator.stop()
    global _camera_watchdog_task
    if _camera_watchdog_task:
        _camera_watchdog_task.cancel()
        _camera_watchdog_task = None


def _require_orchestrator() -> Orchestrator:
    if not _orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not ready")
    return _orchestrator


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "name": "Didier"}


@app.get("/", response_class=HTMLResponse)
async def index() -> str:
    if INDEX_PATH.exists():
        return INDEX_PATH.read_text(encoding="utf-8")
    return "<h1>Didier</h1><p>UI not found.</p>"


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
    if device_ok and pcie_ok and pcie_path:
        runtime_path = None
        hailo_dir = pcie_path / "hailo_chardev"
        if hailo_dir.exists():
            for child in hailo_dir.iterdir():
                candidate = child / "power" / "runtime_active_time"
                if candidate.exists():
                    runtime_path = candidate
                    break
        if runtime_path and runtime_path.exists():
            try:
                active = int(runtime_path.read_text().strip())
                now = time.time()
                with _NPU_CACHE_LOCK:
                    last_active = _NPU_CACHE.get("active")
                    last_ts = _NPU_CACHE.get("ts", 0.0)
                    _NPU_CACHE["active"] = active
                    _NPU_CACHE["ts"] = now
                    if last_active is not None and last_ts:
                        delta_active = max(0, active - last_active)
                        delta_wall = max(0.001, now - last_ts)
                        # runtime_active_time is usually in microseconds
                        active_seconds = delta_active / 1_000_000
                        utilization = int(
                            max(0, min(100, (active_seconds / delta_wall) * 100))
                        )
                        _NPU_CACHE["util"] = utilization
                    else:
                        utilization = _NPU_CACHE.get("util")
            except Exception:
                utilization = None
    return {"available": device_ok and pcie_ok, "utilization": utilization}


def _read_asr_status() -> dict[str, Any]:
    status = read_status()
    status.setdefault("listening", False)
    status.setdefault("thinking", False)
    status.setdefault("speaking", False)
    status.setdefault("state", "IDLE")
    return status


def _load_openclaw_prompt(config: Any) -> str:
    workspace = config.get("openclaw.workspace", "")
    files = config.get(
        "openclaw.bootstrap_files", ["AGENTS.md", "MEMORY.md", "SOUL.md", "USER.md", "TOOLS.md"]
    )
    if not workspace:
        return ""
    root = Path(workspace)
    if not root.exists():
        return ""
    sections = []
    for name in files:
        path = root / name
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").strip()
        if content:
            sections.append(f"### {name}\n{content}")
    return "\n\n".join(sections).strip()


def _read_mic_level(
    alsa_device: str, sample_rate: int, channels: int = 1, cooldown: float = 1.5
) -> dict[str, Any]:
    if not alsa_device:
        return {"available": False, "level_percent": None, "listening": False}
    if shutil.which("arecord") is None:
        return {"available": False, "level_percent": None, "listening": False}
    now = time.time()
    with _AUDIO_CACHE_LOCK:
        if now - _AUDIO_CACHE["ts"] < cooldown and _AUDIO_CACHE["level"] is not None:
            return {
                "available": bool(_AUDIO_CACHE["available"]),
                "level_percent": _AUDIO_CACHE["level"],
                "cached": True,
                "listening": False,
            }

    status = _read_asr_status()
    if status.get("listening"):
        with _AUDIO_CACHE_LOCK:
            cached_level = _AUDIO_CACHE["level"]
        return {
            "available": True,
            "level_percent": cached_level,
            "listening": True,
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
        result = subprocess.run(
            cmd, capture_output=True, check=False, timeout=2
        )
        data = result.stdout or b""
        if not data:
            level_percent = 0
        else:
            rms = audioop.rms(data, 2)
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


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    cpu_per_core = psutil.cpu_percent(interval=0.1, percpu=True)
    if cpu_per_core:
        cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 1)
    else:
        cpu_percent = psutil.cpu_percent(interval=0.1)
    mem = psutil.virtual_memory()
    orchestrator = _require_orchestrator()
    alsa_device = orchestrator.config.get("asr.alsa_device", "default")
    sample_rate = int(orchestrator.config.get("asr.sample_rate", 16000))
    channels = int(orchestrator.config.get("asr.channels", 1))
    npu_device = orchestrator.config.get("npu.device", "/dev/hailo0")
    npu_pcie = orchestrator.config.get("npu.pcie_address", "0001:01:00.0")
    didier_model = orchestrator.config.get("ollama.model", None)
    clawbot_model = orchestrator.config.get("clawbot.model", None)
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
    disk_root = _disk_usage(host_root, "/")
    disk_ssd = (
        _disk_usage(ssd_path, ssd_mount)
        if ssd_path
        else {"available": False, "path": ssd_mount}
    )
    audio = await asyncio.to_thread(_read_mic_level, alsa_device, sample_rate, channels)
    return {
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
            "root": disk_root,
            "ssd": disk_ssd,
            "percent": disk_root.get("percent", 0),
        },
        "npu": _read_npu_usage(npu_device, npu_pcie),
        "audio": audio,
    }


def _read_version() -> dict[str, Any]:
    git_hash = None
    try:
        result = subprocess.run(
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

    return {"git": git_hash, "version": file_version}


async def _resolve_ollama_model(
    base_url: str, preferred: str, fallback: str | None = None
) -> str:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
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
        result = subprocess.run(
            ["pactl", "list", "short", "sinks"],
            capture_output=True,
            text=True,
            check=True,
        )
        available = sink_name in result.stdout
        return {"available": available, "sink": sink_name}
    except Exception as exc:
        return {"available": False, "sink": sink_name, "error": str(exc)}


def _camera_holders(device: str | None) -> dict[str, Any]:
    if not device:
        return {"output": "Aucun périphérique configuré"}
    if shutil.which("fuser") is None:
        return {"output": "fuser indisponible"}
    verbose = subprocess.run(
        ["fuser", "-v", device], capture_output=True, text=True, check=False
    )
    plain = subprocess.run(
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
        ps = subprocess.run(
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
        result = subprocess.run(["fuser", device], capture_output=True, text=True, check=False)
        tokens = (result.stdout or "").replace(":", " ").split()
        for token in tokens:
            if token.isdigit():
                pids.append(int(token))
        subprocess.run(["fuser", "-k", device], check=False)
    # Kill known camera processes as a fallback
    for name in ["libcamera-vid", "libcamera-still", "libcamera-hello", "rpicam-vid", "rpicam-still", "mjpg_streamer", "ffmpeg", "gst-launch-1.0"]:
        subprocess.run(["pkill", "-9", "-f", name], check=False)
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
            subprocess.run(["modprobe", "-r", "uvcvideo"], check=False)
            subprocess.run(["modprobe", "uvcvideo"], check=False)
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
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    return {"status": "format tenté", "output": output.strip()}


def _check_camera(index: int, device: str | None) -> dict[str, Any]:
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


def _check_tts(model_path: str | None, config_path: str | None) -> dict[str, Any]:
    model_ok = Path(model_path).exists() if model_path else False
    config_ok = Path(config_path).exists() if config_path else False
    paplay_ok = shutil.which("paplay") is not None
    return {"model": model_ok, "config": config_ok, "paplay": paplay_ok}


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
        if not result.get("opened") or not result.get("frame"):
            _camera_reconnect(camera_device)


@app.get("/device-status")
async def device_status() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
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

    camera = await asyncio.to_thread(_check_camera, camera_index, camera_device)
    camera_usb = await asyncio.to_thread(_check_camera_usb, vendor, product)
    mic = await asyncio.to_thread(_check_camera_mic)
    sound = await asyncio.to_thread(_check_soundboks_sink, sink)
    npu = await asyncio.to_thread(_check_npu, npu_device, npu_pcie)
    tts = await asyncio.to_thread(_check_tts, tts_model, tts_config)
    version = await asyncio.to_thread(_read_version)

    return {
        "camera": camera,
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


@app.get("/camera/holders")
async def camera_holders() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    return await asyncio.to_thread(_camera_holders, camera_device)


@app.post("/camera/reconnect")
async def camera_reconnect() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    return await asyncio.to_thread(_camera_reconnect, camera_device)


@app.post("/camera/force-format")
async def camera_force_format() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    camera_device = orchestrator.config.get("vision.camera_device", None)
    width = orchestrator.config.get("vision.width", None)
    height = orchestrator.config.get("vision.height", None)
    fourcc = orchestrator.config.get("vision.fourcc", None)
    return await asyncio.to_thread(_camera_force_format, camera_device, width, height, fourcc)


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


def _open_camera(
    device: str | None,
    index: int,
    width: int | None,
    height: int | None,
    fps: int | None,
    fourcc: str | None,
    kill_on_open: bool = False,
) -> cv2.VideoCapture:
    if kill_on_open and device and shutil.which("fuser"):
        try:
            subprocess.run(["fuser", "-k", device], check=False)
        except Exception:
            pass
    if device:
        cap = cv2.VideoCapture(device)
        if cap.isOpened():
            _apply_camera_settings(cap, width, height, fps, fourcc)
            return cap
        cap.release()
        cap = cv2.VideoCapture(device, cv2.CAP_V4L2)
        if cap.isOpened():
            _apply_camera_settings(cap, width, height, fps, fourcc)
            return cap
    cap = cv2.VideoCapture(index)
    if cap.isOpened():
        _apply_camera_settings(cap, width, height, fps, fourcc)
        return cap
    cap.release()
    cap = cv2.VideoCapture(index, cv2.CAP_V4L2)
    _apply_camera_settings(cap, width, height, fps, fourcc)
    return cap


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
    cap = _open_camera(
        camera_device, camera_index, width, height, fps, fourcc, kill_on_open
    )
    if not cap.isOpened():
        cap.release()
        if camera_device:
            try:
                yield from _mjpeg_generator_v4l2(
                    camera_device, width, height, fps, fourcc
                )
            finally:
                _VIDEO_LOCK.release()
            return
        _VIDEO_LOCK.release()
        raise RuntimeError("Unable to open camera")
    failures = 0
    reopen_attempts = 0
    try:
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
            time.sleep(0.03)
    finally:
        cap.release()
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
        time.sleep(0.03)


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
    subprocess.run(fmt_cmd, check=False)
    if fps:
        subprocess.run(
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
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    if not proc.stdout:
        proc.terminate()
        raise RuntimeError("v4l2-ctl stdout unavailable")
    bytes_per_pixel = 2
    if fourcc in {"GRBG", "RGGB", "GBRG", "BGGR"}:
        bytes_per_pixel = 1
    frame_size = width * height * bytes_per_pixel

    def read_exact(size: int) -> bytes | None:
        data = b""
        while len(data) < size:
            chunk = proc.stdout.read(size - len(data))
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
            time.sleep(0.03)
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:
            proc.kill()


@app.get("/video/stream")
async def video_stream() -> StreamingResponse:
    orchestrator = _require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if vision and orchestrator.config.get("vision.enable_live", False):
        if hasattr(vision, "get_latest_jpeg"):
            return StreamingResponse(
                _mjpeg_generator_from_vision(vision),
                media_type="multipart/x-mixed-replace; boundary=frame",
            )
    camera_index = int(orchestrator.config.get("vision.camera_index", 0))
    camera_device = orchestrator.config.get("vision.camera_device", None)
    width = orchestrator.config.get("vision.width", None)
    height = orchestrator.config.get("vision.height", None)
    fps = orchestrator.config.get("vision.fps", None)
    fourcc = orchestrator.config.get("vision.fourcc", None)
    kill_on_open = bool(orchestrator.config.get("vision.kill_on_open", False))
    if _VIDEO_LOCK.locked():
        raise HTTPException(status_code=409, detail="Camera busy")
    try:
        _open_camera(
            camera_device, camera_index, width, height, fps, fourcc, kill_on_open
        ).release()
    except Exception:
        raise HTTPException(status_code=503, detail="Camera not available")
    return StreamingResponse(
        _mjpeg_generator(
            camera_device, camera_index, width, height, fps, fourcc, kill_on_open
        ),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    orchestrator = _require_orchestrator()
    vocal = orchestrator.get_tentacle("vocal")
    if not vocal:
        raise HTTPException(status_code=503, detail="vocal tentacle not loaded")
    await vocal.speak(text)
    return {"status": "queued"}


@app.post("/music/play")
async def music_play(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip() or "musique"
    orchestrator = _require_orchestrator()
    music = orchestrator.get_tentacle("music")
    if not music:
        raise HTTPException(status_code=503, detail="music tentacle not loaded")
    await music.play(prompt)
    return {"status": "queued", "prompt": prompt}


@app.post("/audio/test")
async def audio_test() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    sink = orchestrator.config.get("bluetooth.sink_name", "")
    path = Path("data/soundboks_test.wav")
    try:
        import numpy as np

        sample_rate = 22050
        segments = [
            (0.12, 1.0),
            (0.08, 0.8),
            (0.12, 0.6),
        ]
        audio = np.zeros(0, dtype=np.float32)
        for duration, gain in segments:
            n = int(sample_rate * duration)
            t = np.linspace(0, duration, n, False)
            noise = np.random.uniform(-1, 1, n).astype(np.float32)
            tone = np.sin(2 * np.pi * (500 + 200 * np.exp(-t * 8)) * t).astype(
                np.float32
            )
            envelope = np.exp(-t * 12).astype(np.float32)
            bark = gain * envelope * (0.6 * noise + 0.4 * tone)
            audio = np.concatenate([audio, bark, np.zeros(int(sample_rate * 0.05))])
        audio = np.clip(audio, -1.0, 1.0)
        sf.write(str(path), audio, sample_rate)
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to generate test audio")

    cmd = ["paplay"]
    if sink:
        cmd += ["-d", sink]
    cmd.append(str(path))
    try:
        await asyncio.to_thread(subprocess.run, cmd, check=True)
    except Exception:
        raise HTTPException(status_code=500, detail="paplay failed")
    return {"status": "played", "sink": sink}


@app.post("/ask")
async def ask(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = _require_orchestrator()
    brain = orchestrator.get_tentacle("brain")
    if not brain:
        raise HTTPException(status_code=503, detail="brain tentacle not loaded")
    try:
        update_status(
            thinking=True,
            state="THINKING",
            last_prompt=prompt,
            last_prompt_at=time.time(),
        )
        response = await brain.generate(prompt)
        update_status(
            thinking=False,
            state="IDLE",
            last_response=response,
            last_response_at=time.time(),
        )
    except Exception as exc:
        update_status(thinking=False, state="IDLE", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return {"response": response}


@app.post("/coding")
async def coding(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = _require_orchestrator()
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    model = orchestrator.config.get("coding.model", orchestrator.config.get("ollama.model"))
    num_predict = orchestrator.config.get("coding.num_predict", 400)
    temperature = orchestrator.config.get("coding.temperature", 0.2)
    system_prompt = orchestrator.config.get("coding.system_prompt", "").strip()

    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\nUser: {prompt}\nAssistant:"

    payload_data = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    url = f"{base_url}/api/generate"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return {"response": str(data.get("response", "")).strip()}


@app.post("/clawbot")
async def clawbot(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = _require_orchestrator()
    config = orchestrator.config
    base_url = config.get("ollama.base_url", "http://localhost:11434")
    model = config.get(
        "clawbot.model",
        config.get("coding.model", config.get("ollama.model")),
    )
    num_predict = config.get(
        "clawbot.num_predict",
        config.get("coding.num_predict", config.get("ollama.num_predict", 200)),
    )
    temperature = config.get(
        "clawbot.temperature",
        config.get("coding.temperature", config.get("ollama.temperature", 0.4)),
    )
    system_prompt = config.get(
        "clawbot.system_prompt",
        "Tu es Clawbot, un agent OpenClaw. Tu réponds en français, brièvement, et tu suis AGENTS/TOOLS/SOUL/USER.",
    ).strip()
    model = await _resolve_ollama_model(base_url, model, config.get("ollama.model"))
    memory_path = config.get("memory.path", "data/memory.json")
    max_items = int(config.get("memory.max_items", 200))
    max_chars = int(config.get("memory.max_chars", 8000))
    memory = MemoryStore(memory_path, max_items=max_items, max_chars=max_chars)
    memory_context = memory.render()
    openclaw_prompt = _load_openclaw_prompt(config)

    parts = []
    if openclaw_prompt:
        parts.append(openclaw_prompt)
    if memory_context:
        parts.append(f"### MÉMOIRE PERSISTANTE\n{memory_context}")
    if system_prompt:
        parts.append(system_prompt)
    parts.append(f"User: {prompt}\nClawbot:")
    full_prompt = "\n\n".join(parts)

    payload_data = {
        "model": model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    url = f"{base_url}/api/generate"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    response_text = str(data.get("response", "")).strip()
    memory.add("user", prompt)
    memory.add("assistant", response_text)
    workspace = config.get("openclaw.workspace", "")
    if workspace:
        memory.write_openclaw_memory(Path(workspace) / "MEMORY.md")
    return {"response": response_text}


@app.get("/ollama/models")
async def ollama_models() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    base_url = orchestrator.config.get("ollama.base_url", "http://localhost:11434")
    url = f"{base_url}/api/tags"
    try:
        import httpx

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    return data


@app.get("/version")
async def version() -> dict[str, Any]:
    return _read_version()


@app.get("/asr/status")
async def asr_status() -> dict[str, Any]:
    return _read_asr_status()


@app.post("/ask-and-speak")
async def ask_and_speak(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = str(payload.get("prompt", "")).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    orchestrator = _require_orchestrator()
    brain = orchestrator.get_tentacle("brain")
    vocal = orchestrator.get_tentacle("vocal")
    music = orchestrator.get_tentacle("music")
    if not brain:
        raise HTTPException(status_code=503, detail="brain tentacle not loaded")
    if music and _is_music_prompt(prompt):
        await music.play(prompt)
        response = "Musique lancée."
        if vocal:
            await vocal.speak(response)
        return {"response": response, "audio": bool(vocal), "music": True}
    try:
        update_status(
            thinking=True,
            state="THINKING",
            last_prompt=prompt,
            last_prompt_at=time.time(),
        )
        response = await brain.generate(prompt)
        update_status(
            thinking=False,
            last_response=response,
            last_response_at=time.time(),
        )
    except Exception as exc:
        update_status(thinking=False, state="IDLE", error=str(exc))
        raise HTTPException(status_code=503, detail=f"Ollama unavailable: {exc}")
    audio_ok = False
    if vocal:
        await vocal.speak(response)
        audio_ok = True
    else:
        update_status(state="IDLE")
    return {"response": response, "audio": audio_ok}


@app.get("/vision/capture")
async def capture() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "capture_once"):
        raise HTTPException(status_code=501, detail="capture not supported")
    image_path = await vision.capture_once()
    return {"path": image_path}


@app.post("/vision/enroll")
async def vision_enroll(payload: dict[str, Any]) -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision or not hasattr(vision, "enroll_owner"):
        raise HTTPException(status_code=503, detail="vision tentacle not ready")
    samples = int(payload.get("samples", 5)) if payload else 5
    result = await asyncio.to_thread(vision.enroll_owner, samples)
    return result


@app.get("/vision/owner")
async def vision_owner() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision or not hasattr(vision, "check_owner"):
        raise HTTPException(status_code=503, detail="vision tentacle not ready")
    result = await asyncio.to_thread(vision.check_owner)
    return result


@app.get("/vision/status")
async def vision_status() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "get_status"):
        raise HTTPException(status_code=501, detail="vision status not supported")
    return vision.get_status()


@app.get("/vision/zones")
async def vision_zones() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    width = orchestrator.config.get("vision.width", None)
    height = orchestrator.config.get("vision.height", None)
    zones = orchestrator.config.get("vision.zones", [])
    return {
        "zones": _normalize_zones(zones, width, height),
        "width": width,
        "height": height,
    }


@app.post("/vision/detect")
async def vision_detect() -> dict[str, Any]:
    orchestrator = _require_orchestrator()
    vision = orchestrator.get_tentacle("vision")
    if not vision:
        raise HTTPException(status_code=503, detail="vision tentacle not loaded")
    if not hasattr(vision, "detect_once"):
        raise HTTPException(status_code=501, detail="vision detect not supported")
    return await vision.detect_once()
