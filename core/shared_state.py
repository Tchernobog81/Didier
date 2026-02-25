"""Shared cross-service runtime state (file-backed, lock-protected)."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path(os.getenv("DIDIER_SHARED_STATE_PATH", "data/shared_state.json"))
LOCK_PATH = STATE_PATH.with_suffix(".lock")


def _state_defaults() -> dict[str, Any]:
    return {
        "updated_at": 0.0,
        "metrics": {},
        "workers": {},
        "hardware_profile": {
            "updated_at": 0.0,
            "hash": "",
            "schema": "didier.hardware_profile.v1",
            "source": "network_discovery_v1",
            "host": {},
            "cpu": {},
            "ram": {},
            "npu": {},
            "tpu": {},
            "network_devices": [],
            "discovery": {},
        },
        "arbitration": {
            "ts": 0.0,
            "mode": "NOMINAL",
            "load1": 0.0,
            "limits": {
                "target_fps": 20,
                "drop_frames": False,
                "secondary_stream_enabled": True,
                "verbose_logs": True,
                "pause_asr_ingest": False,
            },
            "active_brakes": {},
            "io": {
                "avg_write_ms": 0.0,
                "samples": 0,
                "queued_writes": 0,
            },
            "triggers": {
                "buffer_overrun_recent": False,
                "io_error_recent": False,
                "audio_queue_size": 0,
            },
        },
    }


def _ensure_parent() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_unlocked() -> dict[str, Any]:
    defaults = _state_defaults()
    if not STATE_PATH.exists():
        return defaults
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(data, dict):
        return defaults

    if not isinstance(data.get("metrics"), dict):
        data["metrics"] = {}
    if not isinstance(data.get("workers"), dict):
        data["workers"] = {}

    hardware_profile = data.get("hardware_profile")
    if not isinstance(hardware_profile, dict):
        data["hardware_profile"] = _state_defaults()["hardware_profile"]
    else:
        if not isinstance(hardware_profile.get("updated_at"), (int, float)):
            hardware_profile["updated_at"] = 0.0
        if not isinstance(hardware_profile.get("hash"), str):
            hardware_profile["hash"] = ""
        if not isinstance(hardware_profile.get("schema"), str):
            hardware_profile["schema"] = "didier.hardware_profile.v1"
        if not isinstance(hardware_profile.get("source"), str):
            hardware_profile["source"] = "network_discovery_v1"
        if not isinstance(hardware_profile.get("host"), dict):
            hardware_profile["host"] = {}
        if not isinstance(hardware_profile.get("cpu"), dict):
            hardware_profile["cpu"] = {}
        if not isinstance(hardware_profile.get("ram"), dict):
            hardware_profile["ram"] = {}
        if not isinstance(hardware_profile.get("npu"), dict):
            hardware_profile["npu"] = {}
        if not isinstance(hardware_profile.get("tpu"), dict):
            hardware_profile["tpu"] = {}
        if not isinstance(hardware_profile.get("network_devices"), list):
            hardware_profile["network_devices"] = []
        if not isinstance(hardware_profile.get("discovery"), dict):
            hardware_profile["discovery"] = {}

    arbitration = data.get("arbitration")
    if not isinstance(arbitration, dict):
        data["arbitration"] = _state_defaults()["arbitration"]
    else:
        if not isinstance(arbitration.get("mode"), str):
            arbitration["mode"] = "NOMINAL"
        if not isinstance(arbitration.get("ts"), (int, float)):
            arbitration["ts"] = 0.0
        if not isinstance(arbitration.get("load1"), (int, float)):
            arbitration["load1"] = 0.0
        if not isinstance(arbitration.get("limits"), dict):
            arbitration["limits"] = _state_defaults()["arbitration"]["limits"]
        if not isinstance(arbitration.get("active_brakes"), dict):
            arbitration["active_brakes"] = {}
        if not isinstance(arbitration.get("triggers"), dict):
            arbitration["triggers"] = _state_defaults()["arbitration"]["triggers"]
        io_block = arbitration.get("io")
        if not isinstance(io_block, dict):
            arbitration["io"] = _state_defaults()["arbitration"]["io"]
        else:
            if not isinstance(io_block.get("avg_write_ms"), (int, float)):
                io_block["avg_write_ms"] = 0.0
            if not isinstance(io_block.get("samples"), int):
                io_block["samples"] = 0
            if not isinstance(io_block.get("queued_writes"), int):
                io_block["queued_writes"] = 0

    return data


def _write_unlocked(data: dict[str, Any]) -> None:
    payload = json.dumps(data, ensure_ascii=False)
    tmp_path = STATE_PATH.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, STATE_PATH)


def read_state() -> dict[str, Any]:
    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        try:
            return _read_unlocked()
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def update_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    payload = dict(metrics or {})
    payload.setdefault("timestamp", now)
    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked()
            data["metrics"] = payload
            data["updated_at"] = now
            _write_unlocked(data)
            return data
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def update_worker_metrics(worker: str, payload: dict[str, Any]) -> dict[str, Any]:
    key = str(worker or "").strip().lower()
    if not key:
        raise ValueError("worker required")
    now = time.time()
    state = dict(payload or {})
    state.setdefault("ts", now)
    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked()
            workers = data.setdefault("workers", {})
            workers[key] = state
            data["updated_at"] = now
            _write_unlocked(data)
            return data
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _hardware_profile_hash(payload: dict[str, Any]) -> str:
    stable = dict(payload or {})
    stable.pop("updated_at", None)
    stable.pop("hash", None)
    stable.pop("scanned_at", None)
    encoded = json.dumps(
        stable,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def update_hardware_profile(
    payload: dict[str, Any],
    only_on_change: bool = True,
) -> dict[str, Any]:
    now = time.time()
    profile = dict(payload or {})
    if not isinstance(profile.get("network_devices"), list):
        profile["network_devices"] = []
    if not isinstance(profile.get("host"), dict):
        profile["host"] = {}
    if not isinstance(profile.get("cpu"), dict):
        profile["cpu"] = {}
    if not isinstance(profile.get("ram"), dict):
        profile["ram"] = {}
    if not isinstance(profile.get("npu"), dict):
        profile["npu"] = {}
    if not isinstance(profile.get("tpu"), dict):
        profile["tpu"] = {}
    if not isinstance(profile.get("discovery"), dict):
        profile["discovery"] = {}
    profile.setdefault("schema", "didier.hardware_profile.v1")
    profile.setdefault("source", "network_discovery_v1")
    profile_hash = _hardware_profile_hash(profile)

    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked()
            current = data.get("hardware_profile", {})
            current_hash = ""
            if isinstance(current, dict):
                current_hash = str(current.get("hash", "")).strip()
                if not current_hash:
                    current_hash = _hardware_profile_hash(current)
            if only_on_change and current_hash and current_hash == profile_hash:
                return {"changed": False, "profile": current}

            profile["updated_at"] = now
            profile["hash"] = profile_hash
            data["hardware_profile"] = profile
            data["updated_at"] = now
            _write_unlocked(data)
            return {"changed": True, "profile": profile}
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def update_arbitration(payload: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    arbitration = dict(payload or {})
    arbitration.setdefault("ts", now)
    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked()
            data["arbitration"] = arbitration
            data["updated_at"] = now
            _write_unlocked(data)
            return arbitration
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def metrics_snapshot() -> dict[str, Any]:
    data = read_state()
    metrics = dict(data.get("metrics", {}) or {})
    workers = data.get("workers", {}) or {}
    if "workers" not in metrics:
        metrics["workers"] = workers
    if "hardware_profile" not in metrics:
        metrics["hardware_profile"] = data.get("hardware_profile", {})
    if "arbitration" not in metrics:
        metrics["arbitration"] = data.get("arbitration", {})
    return metrics


def arbitration_snapshot() -> dict[str, Any]:
    data = read_state()
    payload = data.get("arbitration", {})
    return dict(payload) if isinstance(payload, dict) else {}
