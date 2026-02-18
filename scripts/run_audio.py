#!/usr/bin/env python3
"""Didier MVP audio worker service (native TTS + playback)."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException
from kokoro_onnx import Kokoro

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.shared_state import update_worker_metrics

AUDIO_HOST = os.getenv("DIDIER_AUDIO_HOST", "127.0.0.1")
AUDIO_PORT = int(os.getenv("DIDIER_AUDIO_PORT", "5013"))
TTS_MODEL_PATH = Path(
    os.getenv(
        "DIDIER_TTS_MODEL_PATH",
        "/mnt/didier_ssd/didier/models/tts/kokoro-v1.0.onnx",
    )
)
TTS_CONFIG_PATH = Path(
    os.getenv(
        "DIDIER_TTS_CONFIG_PATH",
        "/mnt/didier_ssd/didier/models/tts/kokoro-v0.19.json",
    )
)
TTS_VOICES_PATH = Path(
    os.getenv(
        "DIDIER_TTS_VOICES_PATH",
        "/mnt/didier_ssd/didier/models/tts/voices-v1.0.bin",
    )
)
TTS_OUTPUT_PATH = Path(
    os.getenv("DIDIER_TTS_OUTPUT_PATH", "/mnt/didier_ssd/didier/workspace/Didier/data/didier_speaks.wav")
)
TTS_VOICE = os.getenv("DIDIER_TTS_VOICE", "af_bella")
TTS_LANG = os.getenv("DIDIER_TTS_LANG", "fr-fr")
AUDIO_SINK = os.getenv("DIDIER_AUDIO_SINK", "bluez_output.00_07_80_E0_3F_F0.1")
APP_STARTED_AT = time.time()

app = FastAPI(title="Didier MVP Audio", version="0.1.0")

_queue: asyncio.Queue[str] = asyncio.Queue()
_worker_task: asyncio.Task[None] | None = None
_shared_state_task: asyncio.Task[None] | None = None
_kokoro: Kokoro | None = None

audio_state: dict[str, Any] = {
    "model_loaded": False,
    "paplay_ok": False,
    "queue_size": 0,
    "speaking": False,
    "last_speak_ts": 0.0,
    "last_error": None,
    "mode": "init",
}


def _load_model() -> Kokoro:
    if not TTS_MODEL_PATH.exists():
        raise FileNotFoundError(f"Missing model: {TTS_MODEL_PATH}")

    if TTS_VOICES_PATH.exists():
        try:
            return Kokoro(
                model_path=str(TTS_MODEL_PATH),
                voices_path=str(TTS_VOICES_PATH),
            )
        except TypeError:
            # Old kokoro_onnx API fallback.
            pass

    if TTS_CONFIG_PATH.exists():
        return Kokoro(model=str(TTS_MODEL_PATH), config_path=str(TTS_CONFIG_PATH))

    raise FileNotFoundError(
        f"Missing voices/config: {TTS_VOICES_PATH} / {TTS_CONFIG_PATH}"
    )


def _play_file(path: Path) -> None:
    if not shutil.which("paplay"):
        raise RuntimeError("paplay not available in PATH")
    try:
        subprocess.run(["paplay", "-d", AUDIO_SINK, str(path)], check=True)
        return
    except subprocess.CalledProcessError:
        # Fallback to the default sink when the configured Bluetooth sink is unavailable.
        subprocess.run(["paplay", str(path)], check=True)


async def _synthesize_and_play(text: str) -> None:
    if _kokoro is None:
        raise RuntimeError("Kokoro is not initialized")
    if hasattr(_kokoro, "create"):
        wav_data, sample_rate = await asyncio.to_thread(
            _kokoro.create, text, TTS_VOICE, 1.0, TTS_LANG
        )
    else:
        wav_data, sample_rate = await asyncio.to_thread(_kokoro.get_speech_ary, text)
    TTS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(sf.write, str(TTS_OUTPUT_PATH), wav_data, sample_rate)
    await asyncio.to_thread(_play_file, TTS_OUTPUT_PATH)


async def _worker_loop() -> None:
    while True:
        text = await _queue.get()
        audio_state["queue_size"] = _queue.qsize()
        try:
            audio_state["speaking"] = True
            await _synthesize_and_play(text)
            audio_state["last_speak_ts"] = time.time()
            audio_state["last_error"] = None
        except Exception as exc:  # pragma: no cover
            audio_state["last_error"] = str(exc)
        finally:
            audio_state["speaking"] = False
            _queue.task_done()
            audio_state["queue_size"] = _queue.qsize()


async def _publish_shared_state_loop() -> None:
    while True:
        healthy = bool(audio_state["model_loaded"] and audio_state["paplay_ok"])
        payload = {
            "status": "ok" if healthy else "degraded",
            "service": "didier-audio",
            "uptime_s": round(time.time() - APP_STARTED_AT, 3),
            "detail": "ready" if healthy else (audio_state["last_error"] or "audio_not_ready"),
            "queue_size": int(audio_state["queue_size"]),
            "speaking": bool(audio_state["speaking"]),
            "mode": str(audio_state["mode"]),
        }
        await asyncio.to_thread(update_worker_metrics, "audio", payload)
        await asyncio.sleep(0.5)


def _generate_beep(path: Path) -> None:
    sample_rate = 22050
    duration = 0.18
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    tone = 0.6 * np.sin(2 * np.pi * 880 * t)
    envelope = np.exp(-t * 18)
    audio = (tone * envelope).astype(np.float32)
    sf.write(str(path), audio, sample_rate)


@app.on_event("startup")
async def _startup() -> None:
    global _kokoro, _worker_task, _shared_state_task
    audio_state["paplay_ok"] = bool(shutil.which("paplay"))
    try:
        _kokoro = await asyncio.to_thread(_load_model)
        audio_state["model_loaded"] = True
        audio_state["mode"] = "ready"
    except Exception as exc:
        audio_state["model_loaded"] = False
        audio_state["mode"] = "degraded"
        audio_state["last_error"] = str(exc)
    _worker_task = asyncio.create_task(_worker_loop())
    _shared_state_task = asyncio.create_task(_publish_shared_state_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _shared_state_task
    if _worker_task:
        _worker_task.cancel()
        try:
            await _worker_task
        except asyncio.CancelledError:
            pass
    if _shared_state_task:
        _shared_state_task.cancel()
        try:
            await _shared_state_task
        except asyncio.CancelledError:
            pass


@app.get("/health")
async def health() -> dict[str, Any]:
    healthy = bool(audio_state["model_loaded"] and audio_state["paplay_ok"])
    now = time.time()
    detail = "ready" if healthy else (audio_state["last_error"] or "audio_not_ready")
    return {
        "status": "ok" if healthy else "degraded",
        "service": "didier-audio",
        "uptime_s": round(now - APP_STARTED_AT, 3),
        "ts": now,
        "detail": detail,
        "model_loaded": bool(audio_state["model_loaded"]),
        "paplay_ok": bool(audio_state["paplay_ok"]),
        "queue_size": int(audio_state["queue_size"]),
        "mode": str(audio_state["mode"]),
    }


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    return {
        "service": "didier-audio",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "queue_size": int(audio_state["queue_size"]),
        "speaking": bool(audio_state["speaking"]),
        "last_speak_ts": float(audio_state["last_speak_ts"]),
        "last_error": audio_state["last_error"],
        "output_path": str(TTS_OUTPUT_PATH),
    }


@app.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text", "")).strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    if not audio_state["model_loaded"]:
        detail = audio_state["last_error"] or "TTS model not ready"
        raise HTTPException(status_code=503, detail=str(detail))
    await _queue.put(text)
    audio_state["queue_size"] = _queue.qsize()
    return {"status": "queued", "queue_size": int(audio_state["queue_size"])}


@app.post("/beep")
async def beep() -> dict[str, Any]:
    if not shutil.which("paplay"):
        raise HTTPException(status_code=503, detail="paplay not available")
    path = Path("/tmp/didier_worker_beep.wav")
    try:
        await asyncio.to_thread(_generate_beep, path)
        await asyncio.to_thread(_play_file, path)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    finally:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass
    return {"status": "ok"}


def main() -> int:
    socket_path = os.getenv("DIDIER_AUDIO_SOCK", "/tmp/didier_audio.sock").strip()
    if socket_path:
        try:
            Path(socket_path).unlink(missing_ok=True)
        except Exception:
            pass
        uvicorn.run(app, uds=socket_path, log_level="info")
    else:
        uvicorn.run(app, host=AUDIO_HOST, port=AUDIO_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
