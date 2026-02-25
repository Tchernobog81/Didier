#!/usr/bin/env python3
"""Didier MVP audio worker service (native TTS + playback)."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
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
TTS_REQUESTED_VOICE = os.getenv("DIDIER_TTS_VOICE", "ff_siwis")
TTS_LANG = os.getenv("DIDIER_TTS_LANG", "fr-fr")
TTS_SPEED = max(0.8, min(float(os.getenv("DIDIER_TTS_SPEED", "1.15")), 1.8))
TTS_MAX_CHARS = max(40, min(int(os.getenv("DIDIER_TTS_MAX_CHARS", "240")), 800))
AUDIO_SINK = os.getenv("DIDIER_AUDIO_SINK", "bluez_output.00_07_80_E0_3F_F0.1")
AUDIO_SOCKET_PATH = os.getenv("DIDIER_AUDIO_SOCK", "/tmp/didier_audio.sock").strip()
AUDIO_QUEUE_MAXSIZE = max(1, min(int(os.getenv("DIDIER_AUDIO_QUEUE_MAXSIZE", "8")), 64))
AUDIO_SHARED_STATE_INTERVAL_S = max(
    0.5, min(float(os.getenv("DIDIER_AUDIO_SHARED_STATE_INTERVAL_S", "1.0")), 5.0)
)
AUDIO_PLAY_TIMEOUT_S = max(2.0, min(float(os.getenv("DIDIER_AUDIO_PLAY_TIMEOUT_S", "8.0")), 20.0))
APP_STARTED_AT = time.time()
LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"

app = FastAPI(title="Didier MVP Audio", version="0.1.0")

_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=AUDIO_QUEUE_MAXSIZE)
_worker_task: asyncio.Task[None] | None = None
_shared_state_task: asyncio.Task[None] | None = None
_kokoro: Kokoro | None = None
_tts_voice_active = TTS_REQUESTED_VOICE
_play_process_lock = threading.Lock()
_play_process: subprocess.Popen[Any] | None = None
_skip_current_output = threading.Event()

audio_state: dict[str, Any] = {
    "model_loaded": False,
    "paplay_ok": False,
    "queue_size": 0,
    "queue_maxsize": AUDIO_QUEUE_MAXSIZE,
    "queue_dropped": 0,
    "playback_interrupted": 0,
    "speaking": False,
    "last_speak_ts": 0.0,
    "last_error": None,
    "mode": "init",
    "tts_voice": _tts_voice_active,
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


def _available_voices(kokoro: Kokoro) -> list[str]:
    getter = getattr(kokoro, "get_voices", None)
    if not callable(getter):
        return []
    try:
        payload = getter()
    except Exception:
        return []
    if isinstance(payload, dict):
        return sorted(str(key) for key in payload.keys() if str(key).strip())
    if isinstance(payload, (list, tuple, set)):
        return sorted(str(item) for item in payload if str(item).strip())
    return []


def _resolve_tts_voice(kokoro: Kokoro, requested_voice: str, lang: str) -> str:
    voice = str(requested_voice or "").strip() or "ff_siwis"
    candidates = _available_voices(kokoro)
    if not candidates:
        return voice

    lang_norm = str(lang or "").strip().lower()
    if lang_norm.startswith("fr"):
        if voice.startswith("ff_") and voice in candidates:
            return voice
        if "ff_siwis" in candidates:
            return "ff_siwis"
        fr_candidates = [item for item in candidates if item.startswith("ff_")]
        if fr_candidates:
            return fr_candidates[0]
    if voice in candidates:
        return voice
    return candidates[0]


def _play_file(path: Path) -> None:
    if not shutil.which("paplay"):
        raise RuntimeError("paplay not available in PATH")

    def _run_once(cmd: list[str]) -> int:
        global _play_process
        proc: subprocess.Popen[Any] | None = None
        try:
            proc = subprocess.Popen(cmd)
            with _play_process_lock:
                _play_process = proc
            try:
                return int(proc.wait(timeout=AUDIO_PLAY_TIMEOUT_S))
            except subprocess.TimeoutExpired:
                try:
                    proc.terminate()
                except Exception:
                    pass
                try:
                    proc.wait(timeout=0.6)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                return 124
        finally:
            with _play_process_lock:
                if _play_process is proc:
                    _play_process = None

    rc = _run_once(["paplay", "-d", AUDIO_SINK, str(path)])
    if rc == 0:
        return
    # Fallback to the default sink when the configured Bluetooth sink is unavailable.
    fallback_rc = _run_once(["paplay", str(path)])
    if fallback_rc != 0:
        raise RuntimeError(f"paplay failed (sink_rc={rc}, fallback_rc={fallback_rc})")


def _interrupt_playback() -> bool:
    with _play_process_lock:
        proc = _play_process
    if proc is None:
        return False
    if proc.poll() is not None:
        return False
    try:
        proc.terminate()
    except Exception:
        return False
    return True


def _sanitize_tts_text(text: str) -> str:
    message = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(message) <= TTS_MAX_CHARS:
        return message
    clipped = message[:TTS_MAX_CHARS].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    return clipped.rstrip(" ,;:") + "."


async def _synthesize_and_play(text: str) -> None:
    if _kokoro is None:
        raise RuntimeError("Kokoro is not initialized")
    if hasattr(_kokoro, "create"):
        wav_data, sample_rate = await asyncio.to_thread(
            _kokoro.create, text, _tts_voice_active, TTS_SPEED, TTS_LANG
        )
    else:
        wav_data, sample_rate = await asyncio.to_thread(_kokoro.get_speech_ary, text)
    if _skip_current_output.is_set():
        return
    TTS_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    await asyncio.to_thread(sf.write, str(TTS_OUTPUT_PATH), wav_data, sample_rate)
    if _skip_current_output.is_set():
        return
    await asyncio.to_thread(_play_file, TTS_OUTPUT_PATH)


async def _worker_loop() -> None:
    while True:
        text = await _queue.get()
        audio_state["queue_size"] = _queue.qsize()
        try:
            audio_state["speaking"] = True
            _skip_current_output.clear()
            await _synthesize_and_play(text)
            audio_state["last_speak_ts"] = time.time()
            audio_state["last_error"] = None
        except Exception as exc:  # pragma: no cover
            audio_state["last_error"] = str(exc)
        finally:
            audio_state["speaking"] = False
            _skip_current_output.clear()
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
            "playback_interrupted": int(audio_state["playback_interrupted"]),
            "speaking": bool(audio_state["speaking"]),
            "mode": str(audio_state["mode"]),
        }
        await asyncio.to_thread(update_worker_metrics, "audio", payload)
        await asyncio.sleep(AUDIO_SHARED_STATE_INTERVAL_S)


def _generate_beep(path: Path) -> None:
    sample_rate = 22050
    duration = 0.18
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    tone = 0.6 * np.sin(2 * np.pi * 880 * t)
    envelope = np.exp(-t * 18)
    audio = (tone * envelope).astype(np.float32)
    sf.write(str(path), audio, sample_rate)


def _cleanup_socket(socket_path: str) -> None:
    if not socket_path:
        return
    try:
        path = Path(socket_path)
        if path.exists():
            path.unlink()
    except Exception:
        pass


@app.on_event("startup")
async def _startup() -> None:
    global _kokoro, _worker_task, _shared_state_task, _tts_voice_active
    logging.basicConfig(
        level=os.getenv("DIDIER_LOG_LEVEL", "INFO").upper(),
        format=LOG_FORMAT,
    )
    audio_state["paplay_ok"] = bool(shutil.which("paplay"))
    try:
        _kokoro = await asyncio.to_thread(_load_model)
        _tts_voice_active = _resolve_tts_voice(_kokoro, TTS_REQUESTED_VOICE, TTS_LANG)
        audio_state["tts_voice"] = _tts_voice_active
        audio_state["model_loaded"] = True
        audio_state["mode"] = "ready"
        logging.getLogger("didier.audio").info(
            "TTS ready voice=%s lang=%s requested=%s",
            _tts_voice_active,
            TTS_LANG,
            TTS_REQUESTED_VOICE,
        )
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
    _cleanup_socket(AUDIO_SOCKET_PATH)


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
        "playback_interrupted": int(audio_state["playback_interrupted"]),
        "mode": str(audio_state["mode"]),
        "tts_voice": str(audio_state.get("tts_voice") or ""),
        "tts_lang": TTS_LANG,
        "play_timeout_s": AUDIO_PLAY_TIMEOUT_S,
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
        "playback_interrupted": int(audio_state["playback_interrupted"]),
        "output_path": str(TTS_OUTPUT_PATH),
        "tts_voice": str(audio_state.get("tts_voice") or ""),
        "tts_lang": TTS_LANG,
        "play_timeout_s": AUDIO_PLAY_TIMEOUT_S,
    }


@app.post("/speak")
async def speak(payload: dict[str, Any]) -> dict[str, Any]:
    text = _sanitize_tts_text(payload.get("text", ""))
    if not text:
        raise HTTPException(status_code=400, detail="text required")
    if not audio_state["model_loaded"]:
        detail = audio_state["last_error"] or "TTS model not ready"
        raise HTTPException(status_code=503, detail=str(detail))
    drop_pending = bool(payload.get("drop_pending", False))
    interrupt_current = bool(payload.get("interrupt_current", False))
    dropped_pending = 0
    if drop_pending:
        while True:
            try:
                _queue.get_nowait()
                _queue.task_done()
                dropped_pending += 1
            except asyncio.QueueEmpty:
                break
    skip_requested = bool(audio_state.get("speaking", False))
    interrupted = False
    if interrupt_current or drop_pending:
        _skip_current_output.set()
        interrupted = _interrupt_playback()
        if interrupted or skip_requested:
            audio_state["playback_interrupted"] = int(audio_state["playback_interrupted"]) + 1
    try:
        _queue.put_nowait(text)
    except asyncio.QueueFull:
        audio_state["queue_dropped"] = int(audio_state["queue_dropped"]) + 1
        raise HTTPException(status_code=429, detail="audio queue saturated")
    audio_state["queue_size"] = _queue.qsize()
    return {
        "status": "queued",
        "queue_size": int(audio_state["queue_size"]),
        "dropped_pending": int(dropped_pending),
        "interrupted": bool(interrupted),
        "skip_requested": bool(skip_requested),
        "playback_interrupted": int(audio_state["playback_interrupted"]),
    }


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
    if AUDIO_SOCKET_PATH:
        try:
            Path(AUDIO_SOCKET_PATH).unlink(missing_ok=True)
        except Exception:
            pass
        uvicorn.run(app, uds=AUDIO_SOCKET_PATH, log_level="info")
    else:
        uvicorn.run(app, host=AUDIO_HOST, port=AUDIO_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
