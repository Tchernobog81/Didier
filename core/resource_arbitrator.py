"""Passive resource arbitration for Didier runtime QoS."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import psutil

from core.shared_state import arbitration_snapshot as read_arbitration_snapshot
from core.shared_state import read_state
from core.shared_state import update_arbitration

MODE_NOMINAL = "NOMINAL"
MODE_TENDU = "TENDU"
MODE_SURVIE = "SURVIE"
_SUPPORTED_MODES = {MODE_NOMINAL, MODE_TENDU, MODE_SURVIE}

DEFAULT_TICK_S = max(0.5, min(float(os.getenv("DIDIER_ARBITRATOR_TICK_S", "1.0")), 5.0))
DEFAULT_SUBPROCESS_TIMEOUT_S = 2.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


class ResourceArbitrator:
    _instance: "ResourceArbitrator | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "ResourceArbitrator":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._logger = logging.getLogger("ResourceArbitrator")
        self._tick_s = DEFAULT_TICK_S
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._state_lock = threading.Lock()
        self._mode = MODE_NOMINAL
        self._load1 = 0.0
        self._last_buffer_overrun_ts = 0.0
        self._last_io_error_ts = 0.0
        self._last_kernel_probe_ts = 0.0
        self._kernel_probe_interval_s = max(
            2.0,
            min(float(os.getenv("DIDIER_ARBITRATOR_KERNEL_PROBE_S", "8.0")), 60.0),
        )
        self._kernel_fingerprint = ""
        self._audio_backpressure_size = max(
            1,
            min(int(os.getenv("DIDIER_ARBITRATOR_AUDIO_BACKPRESSURE", "5")), 64),
        )
        self._snapshot: dict[str, Any] = self._default_snapshot()

        self._batch_lock = threading.Lock()
        self._batch_by_path: dict[str, list[str]] = {}
        self._queued_writes = 0
        self._last_flush_ts = 0.0
        self._batch_flush_interval_s = max(
            0.25,
            min(float(os.getenv("DIDIER_ARBITRATOR_BATCH_FLUSH_S", "1.0")), 10.0),
        )
        self._batch_max_lines = max(
            4,
            min(int(os.getenv("DIDIER_ARBITRATOR_BATCH_MAX_LINES", "32")), 1024),
        )
        self._io_write_ms_samples: list[float] = []
        self._last_heartbeat_ts = 0.0
        self._heartbeat_interval_s = max(
            2.0,
            min(float(os.getenv("DIDIER_ARBITRATOR_HEARTBEAT_S", "5.0")), 60.0),
        )
        self._last_priority_apply_ts = 0.0
        self._priority_apply_interval_s = max(
            5.0,
            min(float(os.getenv("DIDIER_ARBITRATOR_PRIORITY_APPLY_S", "20.0")), 120.0),
        )

    def start(self) -> None:
        with self._state_lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="didier-resource-arbitrator",
                daemon=True,
            )
            self._thread.start()
        self._logger.info("ResourceArbitrator started (tick=%.2fs).", self._tick_s)

    def stop(self) -> None:
        with self._state_lock:
            thread = self._thread
            self._thread = None
        self._stop_event.set()
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._flush_batched_writes(force=True)
        self._logger.info("ResourceArbitrator stopped.")

    def snapshot(self) -> dict[str, Any]:
        with self._state_lock:
            if self._snapshot:
                return json.loads(json.dumps(self._snapshot))
        payload = read_arbitration_snapshot()
        return payload if isinstance(payload, dict) else self._default_snapshot()

    def request_resource(self, token: str) -> bool:
        key = str(token or "").strip().lower()
        snap = self.snapshot()
        limits = snap.get("limits", {}) if isinstance(snap, dict) else {}
        mode = str(snap.get("mode", MODE_NOMINAL)).upper()
        pause_asr = bool(limits.get("pause_asr_ingest", False))
        secondary_enabled = bool(limits.get("secondary_stream_enabled", True))

        if key in {"asr_ingest", "asr_request"} and pause_asr:
            return False
        if key == "secondary_stream" and not secondary_enabled:
            return False
        if mode == MODE_SURVIE and key in {"npu_inference", "llm_generation", "vision_describe"}:
            return False
        return True

    def get_target_fps(self, default: int = 20) -> int:
        snap = self.snapshot()
        limits = snap.get("limits", {}) if isinstance(snap, dict) else {}
        target = _safe_int(limits.get("target_fps"), default)
        return max(1, min(target, 60))

    def should_pause_asr(self) -> bool:
        snap = self.snapshot()
        limits = snap.get("limits", {}) if isinstance(snap, dict) else {}
        return bool(limits.get("pause_asr_ingest", False))

    def note_event(self, event_type: str, detail: str = "") -> None:
        now = time.time()
        event = str(event_type or "").strip().lower()
        if event == "buffer_overrun":
            self._last_buffer_overrun_ts = now
        elif event == "io_error":
            self._last_io_error_ts = now
        self.queue_batched_write(
            "logs/arbitration.events.jsonl",
            {
                "ts": now,
                "event": event,
                "detail": str(detail or "")[:300],
            },
        )

    def queue_batched_write(self, relative_path: str, payload: dict[str, Any]) -> None:
        rel = str(relative_path or "").strip()
        if not rel:
            return
        if Path(rel).is_absolute():
            return
        try:
            line = json.dumps(payload, ensure_ascii=False)
        except Exception:
            return
        with self._batch_lock:
            bucket = self._batch_by_path.setdefault(rel, [])
            bucket.append(line)
            self._queued_writes += 1

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            started = time.time()
            try:
                self._tick_once()
            except Exception:
                self._logger.exception("Arbitration tick failed.")
            elapsed = max(0.0, time.time() - started)
            wait_s = max(0.0, self._tick_s - elapsed)
            self._stop_event.wait(wait_s)
        self._flush_batched_writes(force=True)

    def _tick_once(self) -> None:
        now = time.time()
        self._probe_kernel_signals(now)
        workers = read_state().get("workers", {})
        workers = workers if isinstance(workers, dict) else {}
        audio_state = workers.get("audio", {})
        audio_state = audio_state if isinstance(audio_state, dict) else {}
        audio_queue_size = _safe_int(audio_state.get("queue_size", 0), 0)
        self._load1 = self._read_load1()
        previous_mode = self._mode
        mode = self._compute_mode(now, self._load1)
        pause_asr = audio_queue_size > self._audio_backpressure_size
        limits = self._limits_for_mode(mode, pause_asr=pause_asr)
        active_brakes = {
            "vision_throttled": int(limits["target_fps"]) < 20,
            "hailo_drop_frames": bool(limits["drop_frames"]),
            "secondary_stream_disabled": not bool(limits["secondary_stream_enabled"]),
            "verbose_logs_disabled": not bool(limits["verbose_logs"]),
            "asr_paused_by_audio_backpressure": bool(limits["pause_asr_ingest"]),
        }
        if mode != previous_mode:
            self._logger.warning(
                "Arbitration mode switch %s -> %s (load1=%.2f).",
                previous_mode,
                mode,
                self._load1,
            )
        self._mode = mode
        self._maybe_apply_io_priorities(now, mode)
        self._emit_heartbeat(now, mode, audio_queue_size)
        self._flush_batched_writes(force=False)

        snapshot = {
            "ts": now,
            "mode": mode,
            "load1": round(float(self._load1), 3),
            "limits": limits,
            "active_brakes": active_brakes,
            "triggers": {
                "buffer_overrun_recent": (now - self._last_buffer_overrun_ts) < 20.0,
                "io_error_recent": (now - self._last_io_error_ts) < 45.0,
                "audio_queue_size": audio_queue_size,
            },
            "io": {
                "avg_write_ms": round(self._io_avg_write_ms(), 3),
                "samples": len(self._io_write_ms_samples),
                "queued_writes": self._queued_writes,
            },
        }
        with self._state_lock:
            self._snapshot = snapshot
        update_arbitration(snapshot)

    def _read_load1(self) -> float:
        try:
            return float(os.getloadavg()[0])
        except Exception:
            return 0.0

    def _compute_mode(self, now: float, load1: float) -> str:
        buffer_recent = (now - self._last_buffer_overrun_ts) < 20.0
        io_recent = (now - self._last_io_error_ts) < 45.0
        if self._mode == MODE_SURVIE:
            # Hold SURVIE only while load remains critically high.
            if io_recent or load1 >= 3.0:
                return MODE_SURVIE
            if buffer_recent or load1 >= 1.2:
                return MODE_TENDU
            return MODE_NOMINAL
        if self._mode == MODE_TENDU:
            if io_recent or load1 >= 3.0:
                return MODE_SURVIE
            if buffer_recent or load1 > 1.0:
                return MODE_TENDU
            return MODE_NOMINAL
        if io_recent or load1 > 3.0:
            return MODE_SURVIE
        if buffer_recent or load1 > 1.5:
            return MODE_TENDU
        return MODE_NOMINAL

    def _limits_for_mode(self, mode: str, *, pause_asr: bool) -> dict[str, Any]:
        normalized = str(mode or MODE_NOMINAL).upper()
        if normalized not in _SUPPORTED_MODES:
            normalized = MODE_NOMINAL
        if normalized == MODE_SURVIE:
            return {
                "target_fps": 6,
                "drop_frames": True,
                "secondary_stream_enabled": False,
                "verbose_logs": False,
                "audio_profile": "degraded",
                "llm_profile": "compact",
                "pause_asr_ingest": bool(pause_asr),
            }
        if normalized == MODE_TENDU:
            return {
                "target_fps": 10,
                "drop_frames": True,
                "secondary_stream_enabled": True,
                "verbose_logs": True,
                "audio_profile": "high",
                "llm_profile": "full",
                "pause_asr_ingest": bool(pause_asr),
            }
        return {
            "target_fps": 20,
            "drop_frames": False,
            "secondary_stream_enabled": True,
            "verbose_logs": True,
            "audio_profile": "high",
            "llm_profile": "full",
            "pause_asr_ingest": bool(pause_asr),
        }

    def _probe_kernel_signals(self, now: float) -> None:
        if (now - self._last_kernel_probe_ts) < self._kernel_probe_interval_s:
            return
        self._last_kernel_probe_ts = now
        since_window_s = max(3, int(self._kernel_probe_interval_s) + 2)
        cmd = [
            "journalctl",
            "-k",
            "--since",
            f"{since_window_s} seconds ago",
            "--no-pager",
        ]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=DEFAULT_SUBPROCESS_TIMEOUT_S,
            )
        except Exception:
            return
        raw = (result.stdout or "") + "\n" + (result.stderr or "")
        tail = "\n".join(raw.splitlines()[-120:])
        fingerprint = hashlib.sha1(tail.encode("utf-8", errors="ignore")).hexdigest()
        if fingerprint == self._kernel_fingerprint:
            return
        self._kernel_fingerprint = fingerprint
        lowered = tail.lower()
        if any(
            marker in lowered
            for marker in (
                "buffer overrun event",
                "xhci_hcd buffer overrun",
                "xhci-hcd buffer overrun",
                "usb babble detected",
            )
        ):
            self._last_buffer_overrun_ts = now
        if any(
            marker in lowered
            for marker in (
                "i/o error",
                "blk_update_request",
                "ext4-fs error",
            )
        ):
            self._last_io_error_ts = now

    def _maybe_apply_io_priorities(self, now: float, mode: str) -> None:
        if mode == MODE_SURVIE:
            force = True
        else:
            force = (now - self._last_priority_apply_ts) >= self._priority_apply_interval_s
        if not force:
            return
        self._last_priority_apply_ts = now
        self._raise_self_priority()
        for proc in psutil.process_iter(attrs=["pid", "name", "cmdline"]):
            try:
                name = str(proc.info.get("name", "")).lower()
                cmdline = " ".join(proc.info.get("cmdline", [])).lower()
                proc_view = f"{name} {cmdline}"
                if "sshd" in proc_view or ("uvicorn" in proc_view and "core.api:app" in proc_view):
                    self._set_proc_io_prio(proc, high=True)
                elif any(
                    token in proc_view
                    for token in (
                        "run_vision.py",
                        "ffmpeg",
                        "gst-launch-1.0",
                        "hailortcli",
                    )
                ):
                    self._set_proc_io_prio(proc, high=False)
            except Exception:
                continue

    def _raise_self_priority(self) -> None:
        try:
            os.nice(-2)
        except Exception:
            return

    def _set_proc_io_prio(self, proc: psutil.Process, *, high: bool) -> None:
        try:
            if not hasattr(proc, "ionice"):
                return
            if high:
                if hasattr(psutil, "IOPRIO_CLASS_BE"):
                    proc.ionice(psutil.IOPRIO_CLASS_BE, value=0)
            else:
                if hasattr(psutil, "IOPRIO_CLASS_IDLE"):
                    proc.ionice(psutil.IOPRIO_CLASS_IDLE)
                try:
                    if proc.nice() < 10:
                        proc.nice(10)
                except Exception:
                    pass
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return
        except Exception:
            return

    def _emit_heartbeat(self, now: float, mode: str, audio_queue_size: int) -> None:
        if (now - self._last_heartbeat_ts) < self._heartbeat_interval_s:
            return
        self._last_heartbeat_ts = now
        self.queue_batched_write(
            "logs/arbitration.jsonl",
            {
                "ts": now,
                "mode": mode,
                "load1": round(self._load1, 3),
                "audio_queue_size": int(audio_queue_size),
            },
        )

    def _flush_batched_writes(self, *, force: bool) -> None:
        now = time.time()
        with self._batch_lock:
            if not self._batch_by_path:
                return
            if not force:
                ready_by_size = self._queued_writes >= self._batch_max_lines
                ready_by_time = (now - self._last_flush_ts) >= self._batch_flush_interval_s
                if not ready_by_size and not ready_by_time:
                    return
            pending = self._batch_by_path
            self._batch_by_path = {}
            self._queued_writes = 0
            self._last_flush_ts = now
        started = time.perf_counter()
        for rel_path, lines in pending.items():
            try:
                path = Path(rel_path)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as handle:
                    handle.write("\n".join(lines))
                    handle.write("\n")
            except Exception:
                self._logger.debug("Batched write failed: %s", rel_path, exc_info=True)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        self._io_write_ms_samples.append(elapsed_ms)
        if len(self._io_write_ms_samples) > 120:
            self._io_write_ms_samples = self._io_write_ms_samples[-120:]

    def _io_avg_write_ms(self) -> float:
        if not self._io_write_ms_samples:
            return 0.0
        return sum(self._io_write_ms_samples) / len(self._io_write_ms_samples)

    def _default_snapshot(self) -> dict[str, Any]:
        return {
            "ts": 0.0,
            "mode": MODE_NOMINAL,
            "load1": 0.0,
            "limits": self._limits_for_mode(MODE_NOMINAL, pause_asr=False),
            "active_brakes": {},
            "triggers": {
                "buffer_overrun_recent": False,
                "io_error_recent": False,
                "audio_queue_size": 0,
            },
            "io": {
                "avg_write_ms": 0.0,
                "samples": 0,
                "queued_writes": 0,
            },
        }


def get_resource_arbitrator() -> ResourceArbitrator:
    return ResourceArbitrator.get_instance()


def shared_arbitration_snapshot() -> dict[str, Any]:
    payload = read_arbitration_snapshot()
    return payload if isinstance(payload, dict) else {}
