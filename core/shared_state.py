"""Shared cross-service runtime state (file-backed, lock-protected)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import fcntl

STATE_PATH = Path(os.getenv("DIDIER_SHARED_STATE_PATH", "data/shared_state.json"))
LOCK_PATH = STATE_PATH.with_suffix(".lock")


def _ensure_parent() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)


def _read_unlocked() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"updated_at": 0.0, "metrics": {}, "workers": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"updated_at": 0.0, "metrics": {}, "workers": {}}
    if not isinstance(data, dict):
        return {"updated_at": 0.0, "metrics": {}, "workers": {}}
    if not isinstance(data.get("metrics"), dict):
        data["metrics"] = {}
    if not isinstance(data.get("workers"), dict):
        data["workers"] = {}
    return data


def _write_unlocked(data: dict[str, Any]) -> None:
    STATE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


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


def metrics_snapshot() -> dict[str, Any]:
    data = read_state()
    metrics = dict(data.get("metrics", {}) or {})
    workers = data.get("workers", {}) or {}
    if "workers" not in metrics:
        metrics["workers"] = workers
    return metrics

