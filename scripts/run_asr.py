#!/usr/bin/env python3
"""Didier ASR worker (wake word + command relay) with async subprocess I/O."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import shutil
import sys
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import soundfile as sf
import uvicorn
from fastapi import FastAPI, HTTPException

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.status import read_status, update_status
from core.shared_state import update_worker_metrics
from shared.ipc import request as ipc_request


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


ASR_HOST = os.getenv("DIDIER_ASR_HOST", "127.0.0.1")
ASR_PORT = int(os.getenv("DIDIER_ASR_PORT", "5014"))
API_BASE_URL = os.getenv("DIDIER_ASR_API_URL", "http://127.0.0.1:5010")

ASR_ENABLED = _env_bool("DIDIER_ASR_ENABLED", True)
ASR_ALSA_DEVICE = os.getenv("DIDIER_ASR_ALSA_DEVICE", "hw:2,0")
ASR_SAMPLE_RATE = int(os.getenv("DIDIER_ASR_SAMPLE_RATE", "16000"))
ASR_CHANNELS = int(os.getenv("DIDIER_ASR_CHANNELS", "4"))
ASR_CHUNK_SECONDS = int(os.getenv("DIDIER_ASR_CHUNK_SECONDS", "3"))
ASR_COMMAND_CHUNK_SECONDS = int(
    os.getenv("DIDIER_ASR_COMMAND_CHUNK_SECONDS", str(ASR_CHUNK_SECONDS))
)
ASR_WAKE_EVERY_N_CHUNKS = max(1, int(os.getenv("DIDIER_ASR_WAKE_EVERY_N_CHUNKS", "2")))
ASR_LANGUAGE = os.getenv("DIDIER_ASR_LANGUAGE", "fr")
ASR_WHISPER_BIN = os.getenv("DIDIER_ASR_WHISPER_BIN", "").strip()
ASR_MODEL_PATH = os.getenv("DIDIER_ASR_MODEL_PATH", "").strip()
ASR_WAKE_MODEL_PATH = os.getenv("DIDIER_ASR_WAKE_MODEL_PATH", ASR_MODEL_PATH).strip()

_DEFAULT_ASR_THREADS = max(1, min(2, int(os.cpu_count() or 2)))
ASR_THREADS = int(os.getenv("DIDIER_ASR_THREADS", str(_DEFAULT_ASR_THREADS)))
ASR_WAKE_THREADS = int(os.getenv("DIDIER_ASR_WAKE_THREADS", "1"))
ASR_BEAM_SIZE = int(os.getenv("DIDIER_ASR_BEAM_SIZE", "1"))
ASR_BEST_OF = int(os.getenv("DIDIER_ASR_BEST_OF", "1"))
ASR_NO_FALLBACK = _env_bool("DIDIER_ASR_NO_FALLBACK", False)
ASR_NO_TIMESTAMPS = _env_bool("DIDIER_ASR_NO_TIMESTAMPS", True)

ASR_WAKE_WORD = os.getenv("DIDIER_ASR_WAKE_WORD", "Yo! Didier").strip() or "Yo! Didier"
_wake_aliases_raw = os.getenv("DIDIER_ASR_WAKE_WORD_ALIASES", "")
ASR_WAKE_WORD_ALIASES = [x.strip() for x in _wake_aliases_raw.split("|") if x.strip()]
ASR_WAKE_TIMEOUT_SECONDS = float(os.getenv("DIDIER_ASR_WAKE_TIMEOUT_SECONDS", "12"))
ASR_WAKE_REPLY_ENABLED = _env_bool("DIDIER_ASR_WAKE_REPLY_ENABLED", True)
ASR_WAKE_REPLY_TEXT = os.getenv(
    "DIDIER_ASR_WAKE_REPLY_TEXT", "Salut Tcherno, qu'est-ce que je peux faire pour toi ?"
).strip()
ASR_ALLOW_INLINE_COMMAND = _env_bool("DIDIER_ASR_ALLOW_INLINE_COMMAND", False)
ASR_ACTION_TIMEOUT_SECONDS = float(os.getenv("DIDIER_ASR_ACTION_TIMEOUT_SECONDS", "25"))

APP_STARTED_AT = time.time()
TMP_DIR = Path("/tmp")

app = FastAPI(title="Didier ASR Worker", version="0.1.0")
logger = logging.getLogger("didier.asr")

_audio_queue: asyncio.Queue[Path] = asyncio.Queue(maxsize=2)
_capture_task: asyncio.Task[None] | None = None
_process_task: asyncio.Task[None] | None = None
_shared_state_task: asyncio.Task[None] | None = None
_stop_event = asyncio.Event()

_wake_words = [ASR_WAKE_WORD] + ASR_WAKE_WORD_ALIASES
_wake_word_norms: list[str] = []
_wake_word_compact: list[str] = []

asr_state: dict[str, Any] = {
    "enabled": ASR_ENABLED,
    "ready": False,
    "detail": "init",
    "armed": False,
    "armed_until": 0.0,
    "queue_size": 0,
    "idle_chunk_count": 0,
    "capture_failures": 0,
    "last_asr_ms": 0.0,
    "last_error": None,
}


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
    return normalized


def _build_wake_words() -> None:
    _wake_word_norms.clear()
    _wake_word_compact.clear()
    for wake in _wake_words:
        norm = _normalize_text(wake)
        if not norm:
            continue
        _wake_word_norms.append(norm)
        _wake_word_compact.append(norm.replace(" ", ""))


def _matches_wake_word(text: str) -> bool:
    if not _wake_word_norms:
        return False
    normalized = _normalize_text(text)
    compact = normalized.replace(" ", "")
    for wake in _wake_word_norms:
        if wake and wake in normalized:
            return True
    for wake in _wake_word_compact:
        if wake and wake in compact:
            return True
    tokens = normalized.split()
    has_yo = any(tok.startswith("yo") for tok in tokens)
    has_did = any(tok.startswith("didi") or tok.startswith("didie") for tok in tokens)
    if has_yo and has_did:
        return True
    has_y = any(tok.startswith("y") for tok in tokens)
    di_letters = sum(1 for tok in tokens if tok in {"d", "i"})
    if has_y and di_letters >= 3:
        return True
    if compact.startswith("ya") and "ddii" in compact:
        return True
    return False


def _extract_after_wake(text: str) -> str | None:
    normalized = _normalize_text(text)
    for wake in _wake_word_norms:
        if wake and wake in normalized:
            remainder = normalized.replace(wake, "").strip()
            return remainder or None
    return None


async def _run_command(cmd: list[str], timeout_s: float) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        out_b, err_b = await proc.communicate()
        return -1, out_b.decode("utf-8", errors="ignore"), "timeout"
    return (
        int(proc.returncode or 0),
        out_b.decode("utf-8", errors="ignore"),
        err_b.decode("utf-8", errors="ignore"),
    )


async def _api_post(path: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
    response = await ipc_request(
        "POST",
        path,
        service="api",
        base_url=API_BASE_URL,
        payload=payload,
        timeout=timeout_s,
    )
    if not response.is_success:
        detail = f"http {response.status_code}"
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("detail"):
                detail = str(body["detail"])
        except Exception:
            pass
        raise RuntimeError(detail)
    data = response.json()
    return data if isinstance(data, dict) else {"status": "ok"}


def _cleanup_path(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except Exception:
        return


async def _downmix_to_mono(src: Path, dst: Path) -> bool:
    try:
        data, sr = await asyncio.to_thread(sf.read, str(src), dtype="float32")
        if data.ndim > 1:
            rms_by_channel = np.sqrt(np.mean(np.square(data), axis=0))
            best_idx = int(np.argmax(rms_by_channel))
            data = data[:, best_idx]
        peak = float(np.max(np.abs(data))) if data.size else 0.0
        if peak > 1e-6 and peak < 0.2:
            gain = min(12.0, 0.2 / peak)
            data = np.clip(data * gain, -1.0, 1.0)
        await asyncio.to_thread(sf.write, str(dst), data, sr)
        return True
    except Exception:
        return False


async def _transcribe_wav(
    wav_path: Path,
    model_path: str,
    label: str,
    threads: int,
) -> str | None:
    mono_path = wav_path.with_name(f"{wav_path.stem}_mono.wav")
    txt_path = mono_path.with_suffix(".wav.txt")
    ok = await _downmix_to_mono(wav_path, mono_path)
    if not ok:
        _cleanup_path(wav_path)
        return None

    cmd = [
        ASR_WHISPER_BIN,
        "-m",
        model_path,
        "-f",
        str(mono_path),
        "-l",
        ASR_LANGUAGE,
        "-otxt",
        "-t",
        str(max(1, threads)),
        "-bs",
        str(ASR_BEAM_SIZE),
        "-bo",
        str(ASR_BEST_OF),
        "-np",
    ]
    if ASR_NO_FALLBACK:
        cmd.append("-nf")
    if ASR_NO_TIMESTAMPS:
        cmd.append("-nt")

    started = time.time()
    rc, _out, err = await _run_command(cmd, timeout_s=max(20.0, ASR_CHUNK_SECONDS * 8.0))
    if rc != 0:
        asr_state["last_error"] = err.strip() or f"whisper exit {rc}"
        _cleanup_path(wav_path)
        _cleanup_path(mono_path)
        _cleanup_path(txt_path)
        return None
    if not txt_path.exists():
        _cleanup_path(wav_path)
        _cleanup_path(mono_path)
        return None

    text = txt_path.read_text(encoding="utf-8").strip()
    elapsed_ms = (time.time() - started) * 1000.0
    asr_state["last_asr_ms"] = round(elapsed_ms, 2)
    update_status(
        last_asr_ms=int(elapsed_ms),
        last_asr_model=Path(model_path).name,
        last_asr_pass=label,
        asr_worker=True,
    )
    _cleanup_path(wav_path)
    _cleanup_path(mono_path)
    _cleanup_path(txt_path)
    return text or None


async def _on_wake_word() -> None:
    asr_state["armed"] = True
    asr_state["armed_until"] = time.time() + ASR_WAKE_TIMEOUT_SECONDS
    update_status(state="LISTENING", asr_worker=True)
    logger.info("Wake word detected.")
    if ASR_WAKE_REPLY_ENABLED and ASR_WAKE_REPLY_TEXT:
        try:
            await _api_post("/speak", {"text": ASR_WAKE_REPLY_TEXT}, timeout_s=4.0)
        except Exception as exc:
            asr_state["last_error"] = f"wake reply: {exc}"


async def _handle_command(text: str) -> None:
    logger.info("Heard: %s", text)
    update_status(
        last_prompt=text,
        last_prompt_at=time.time(),
        state="LISTENING",
        asr_worker=True,
    )
    try:
        result = await _api_post(
            "/ask-and-speak",
            {"prompt": text},
            timeout_s=max(6.0, ASR_ACTION_TIMEOUT_SECONDS),
        )
        response_text = str(result.get("response", "")).strip()
        if response_text:
            update_status(
                last_response=response_text,
                last_response_at=time.time(),
                state="IDLE",
                asr_worker=True,
            )
    except Exception as exc:
        asr_state["last_error"] = f"command relay: {exc}"
        update_status(state="IDLE", asr_worker=True)


async def _capture_loop() -> None:
    retry_delay = 0.8
    while not _stop_event.is_set():
        ts = int(time.time() * 1000)
        wav_path = TMP_DIR / f"didier_mic_{ts}.wav"
        chunk_seconds = ASR_COMMAND_CHUNK_SECONDS if asr_state["armed"] else ASR_CHUNK_SECONDS
        cmd = [
            "arecord",
            "-D",
            ASR_ALSA_DEVICE,
            "-f",
            "S16_LE",
            "-c",
            str(ASR_CHANNELS),
            "-r",
            str(ASR_SAMPLE_RATE),
            "-d",
            str(chunk_seconds),
            str(wav_path),
        ]
        rc, _out, err = await _run_command(cmd, timeout_s=max(3.0, chunk_seconds + 2.0))
        if rc != 0:
            asr_state["capture_failures"] = int(asr_state["capture_failures"]) + 1
            asr_state["last_error"] = err.strip() or f"arecord exit {rc}"
            _cleanup_path(wav_path)
            await asyncio.sleep(retry_delay)
            retry_delay = min(10.0, retry_delay * 1.8)
            continue
        retry_delay = 0.8
        asr_state["capture_failures"] = 0
        if not wav_path.exists() or wav_path.stat().st_size <= 0:
            _cleanup_path(wav_path)
            continue
        if not asr_state["armed"] and ASR_WAKE_EVERY_N_CHUNKS > 1:
            asr_state["idle_chunk_count"] = int(asr_state["idle_chunk_count"]) + 1
            if int(asr_state["idle_chunk_count"]) % ASR_WAKE_EVERY_N_CHUNKS != 0:
                _cleanup_path(wav_path)
                continue
        if _audio_queue.full():
            _cleanup_path(wav_path)
            continue
        await _audio_queue.put(wav_path)
        asr_state["queue_size"] = _audio_queue.qsize()


async def _process_loop() -> None:
    while not _stop_event.is_set():
        wav_path = await _audio_queue.get()
        asr_state["queue_size"] = _audio_queue.qsize()
        try:
            use_wake_model = not asr_state["armed"]
            model_path = ASR_WAKE_MODEL_PATH if use_wake_model else ASR_MODEL_PATH
            label = "wake" if use_wake_model else "command"
            threads = ASR_WAKE_THREADS if use_wake_model else ASR_THREADS
            text = await _transcribe_wav(
                wav_path,
                model_path=model_path,
                label=label,
                threads=threads,
            )
            if not text:
                continue
            now = time.time()
            update_status(
                last_transcript=text,
                last_heard_at=now,
                listening=True,
                asr_worker=True,
            )
            if not asr_state["armed"]:
                logger.info("Wake candidate transcript: %s", text)
                if _matches_wake_word(text):
                    await _on_wake_word()
                    if ASR_ALLOW_INLINE_COMMAND and ASR_WAKE_MODEL_PATH == ASR_MODEL_PATH:
                        extra = _extract_after_wake(text)
                        if extra:
                            await _handle_command(extra)
                            asr_state["armed"] = False
                else:
                    update_status(state="IDLE", asr_worker=True)
                continue
            if now > float(asr_state["armed_until"]):
                asr_state["armed"] = False
                update_status(state="IDLE", asr_worker=True)
                continue
            await _handle_command(text)
            asr_state["armed"] = False
        except Exception as exc:
            asr_state["last_error"] = str(exc)
        finally:
            _audio_queue.task_done()
            asr_state["queue_size"] = _audio_queue.qsize()


async def _publish_shared_state_loop() -> None:
    while True:
        capture_up = _capture_task is not None and not _capture_task.done()
        process_up = _process_task is not None and not _process_task.done()
        healthy = bool(asr_state["ready"] and capture_up and process_up)
        payload = {
            "status": "ok" if healthy else "degraded",
            "service": "didier-asr",
            "uptime_s": round(time.time() - APP_STARTED_AT, 3),
            "detail": "ready" if healthy else str(asr_state.get("detail") or asr_state.get("last_error") or "not_ready"),
            "queue_size": int(asr_state["queue_size"]),
            "idle_chunk_count": int(asr_state["idle_chunk_count"]),
            "armed": bool(asr_state["armed"]),
            "capture_failures": int(asr_state["capture_failures"]),
            "last_asr_ms": float(asr_state["last_asr_ms"]),
        }
        await asyncio.to_thread(update_worker_metrics, "asr", payload)
        await asyncio.sleep(0.5)


def _validate_prerequisites() -> tuple[bool, str]:
    if not ASR_ENABLED:
        return False, "asr_disabled"
    if shutil.which("arecord") is None:
        return False, "arecord_missing"
    if not ASR_WHISPER_BIN or not Path(ASR_WHISPER_BIN).exists():
        return False, f"whisper_bin_missing:{ASR_WHISPER_BIN}"
    if not ASR_MODEL_PATH or not Path(ASR_MODEL_PATH).exists():
        return False, f"model_missing:{ASR_MODEL_PATH}"
    if not ASR_WAKE_MODEL_PATH or not Path(ASR_WAKE_MODEL_PATH).exists():
        return False, f"wake_model_missing:{ASR_WAKE_MODEL_PATH}"
    return True, "ready"


@app.on_event("startup")
async def _startup() -> None:
    global _capture_task, _process_task, _shared_state_task
    logging.basicConfig(level=logging.INFO)
    _build_wake_words()
    ok, detail = _validate_prerequisites()
    asr_state["ready"] = ok
    asr_state["detail"] = detail
    update_status(
        listening=bool(ok),
        state="LISTENING" if ok else "IDLE",
        asr_worker=True,
        asr_worker_mode=True,
    )
    if not ok:
        _shared_state_task = asyncio.create_task(_publish_shared_state_loop())
        return
    _stop_event.clear()
    _capture_task = asyncio.create_task(_capture_loop())
    _process_task = asyncio.create_task(_process_loop())
    _shared_state_task = asyncio.create_task(_publish_shared_state_loop())


@app.on_event("shutdown")
async def _shutdown() -> None:
    global _shared_state_task
    _stop_event.set()
    for task in (_capture_task, _process_task, _shared_state_task):
        if task is not None:
            task.cancel()
    for task in (_capture_task, _process_task, _shared_state_task):
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
    update_status(listening=False, state="IDLE", asr_worker=True, asr_worker_mode=True)


@app.get("/health")
async def health() -> dict[str, Any]:
    capture_up = _capture_task is not None and not _capture_task.done()
    process_up = _process_task is not None and not _process_task.done()
    healthy = bool(asr_state["ready"] and capture_up and process_up)
    return {
        "status": "ok" if healthy else "degraded",
        "service": "didier-asr",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "detail": "ready" if healthy else str(asr_state.get("detail") or asr_state.get("last_error") or "not_ready"),
        "queue_size": int(asr_state["queue_size"]),
        "armed": bool(asr_state["armed"]),
    }


@app.get("/metrics")
async def metrics() -> dict[str, Any]:
    return {
        "service": "didier-asr",
        "uptime_s": round(time.time() - APP_STARTED_AT, 3),
        "ts": time.time(),
        "queue_size": int(asr_state["queue_size"]),
        "idle_chunk_count": int(asr_state["idle_chunk_count"]),
        "armed": bool(asr_state["armed"]),
        "capture_failures": int(asr_state["capture_failures"]),
        "last_asr_ms": float(asr_state["last_asr_ms"]),
        "last_error": asr_state["last_error"],
    }


@app.post("/wake-test")
async def wake_test(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    if not asr_state["ready"]:
        raise HTTPException(status_code=503, detail=str(asr_state.get("detail", "asr_not_ready")))
    inject_wake_tts = bool(payload.get("inject_wake_tts", True))
    reply_on_wake = bool(payload.get("reply_on_wake", False))
    timeout_s = max(3.0, min(float(payload.get("timeout_seconds", 12.0)), 30.0))
    repeats = max(1, min(int(payload.get("repeats", 2)), 4))
    repeat_gap_s = max(0.2, min(float(payload.get("repeat_gap_seconds", 0.8)), 2.0))

    before = read_status()
    baseline_ts = float(before.get("last_heard_at") or before.get("updated_at") or 0.0)
    baseline_transcript = str(before.get("last_transcript") or "")
    started_at = time.time()

    if inject_wake_tts:
        for idx in range(repeats):
            await _api_post("/speak", {"text": ASR_WAKE_WORD}, timeout_s=4.0)
            if idx < repeats - 1:
                await asyncio.sleep(repeat_gap_s)

    matched = False
    heard_transcript = ""
    heard_at = 0.0
    while time.time() - started_at <= timeout_s:
        await asyncio.sleep(0.25)
        status = read_status()
        transcript = str(status.get("last_transcript") or "").strip()
        ts = float(status.get("last_heard_at") or status.get("updated_at") or 0.0)
        if transcript and ts > baseline_ts:
            heard_transcript = transcript
            heard_at = ts
            if _matches_wake_word(transcript):
                matched = True
                break

    wake_reply_queued = False
    if matched and reply_on_wake and ASR_WAKE_REPLY_ENABLED and ASR_WAKE_REPLY_TEXT:
        await _api_post("/speak", {"text": ASR_WAKE_REPLY_TEXT}, timeout_s=4.0)
        wake_reply_queued = True

    elapsed_s = round(time.time() - started_at, 2)
    final_status = read_status()
    audio_detected = bool(heard_transcript)
    status_value = "ok" if matched else ("audio_only" if audio_detected else "timeout")
    return {
        "status": status_value,
        "wake_word": ASR_WAKE_WORD,
        "wake_words": _wake_words,
        "inject_wake_tts": inject_wake_tts,
        "timeout_seconds": timeout_s,
        "repeats": repeats,
        "elapsed_seconds": elapsed_s,
        "matched": matched,
        "audio_detected": audio_detected,
        "heard_transcript": heard_transcript,
        "heard_at": heard_at or None,
        "wake_reply_queued": wake_reply_queued,
        "wake_reply_text": ASR_WAKE_REPLY_TEXT if wake_reply_queued else "",
        "baseline_transcript": baseline_transcript,
        "asr_state": final_status.get("state"),
        "listening": bool(final_status.get("listening", False)),
    }


def main() -> int:
    uvicorn.run(app, host=ASR_HOST, port=ASR_PORT, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
