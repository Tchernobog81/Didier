"""Shared cross-service runtime state (file-backed, lock-protected)."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

STATE_PATH = Path(os.getenv("DIDIER_SHARED_STATE_PATH", "data/shared_state.json"))
LOCK_PATH = STATE_PATH.with_suffix(".lock")
CONFIG_PATH = Path(os.getenv("DIDIER_CONFIG_PATH", "config/config.json"))

_OPENCLAW_DEFAULT_MEMORY_FILES = (
    "data/openclaw_memory/SOUL.md",
    "data/openclaw_memory/MEMORY.md",
    "openclaw/AGENTS.md",
)
_OPENCLAW_PREVIEW_CHARS = max(
    80,
    min(int(os.getenv("DIDIER_OPENCLAW_MEMORY_PREVIEW_CHARS", "280")), 4000),
)
_OPENCLAW_CONTENT_MAX_CHARS = max(
    200,
    min(int(os.getenv("DIDIER_OPENCLAW_MEMORY_MAX_CHARS", "12000")), 100000),
)


def _state_defaults() -> dict[str, Any]:
    return {
        "updated_at": 0.0,
        "metrics": {},
        "workers": {},
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
        "openclaw": {
            "ts": 0.0,
            "runtime": {"status": "idle", "scheduler_hz": 2.0, "tick": 0},
            "memory_markdown": {
                "loaded_at": 0.0,
                "sync_ok": False,
                "sources": [],
            },
            "tasks": {
                "updated_at": 0.0,
                "items": [],
            },
        },
    }


def _ensure_parent() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)


def _repo_root() -> Path:
    return Path(".").resolve()


def _normalize_path(path: Path) -> str:
    root = _repo_root()
    try:
        return str(path.resolve().relative_to(root))
    except Exception:
        return str(path.resolve())


def _resolve_path(raw: str) -> Path:
    value = str(raw or "").strip()
    if not value:
        return _repo_root()
    path = Path(value)
    if not path.is_absolute():
        path = _repo_root() / path
    return path.resolve()


def _read_config_data() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _memory_file_paths() -> list[Path]:
    config = _read_config_data()
    openclaw_cfg = config.get("openclaw", {}) if isinstance(config, dict) else {}
    raw_files = (
        openclaw_cfg.get("memory_markdown_files")
        if isinstance(openclaw_cfg, dict)
        else None
    )
    if not isinstance(raw_files, list) or not raw_files:
        raw_files = list(_OPENCLAW_DEFAULT_MEMORY_FILES)
    paths: list[Path] = []
    for raw in raw_files:
        value = str(raw or "").strip()
        if not value:
            continue
        paths.append(_resolve_path(value))
    dedup: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        dedup.append(path)
    return dedup


def _allowed_memory_roots() -> list[Path]:
    roots = {
        _resolve_path("openclaw"),
        _resolve_path("data/openclaw_memory"),
    }
    for path in _memory_file_paths():
        roots.add(path.parent.resolve())
    return sorted(roots, key=lambda p: str(p))


def _path_in_allowed_roots(path: Path) -> bool:
    resolved = path.resolve()
    for root in _allowed_memory_roots():
        if resolved == root or root in resolved.parents:
            return True
    return False


def _collect_memory_sources(include_content: bool = False) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for path in _memory_file_paths():
        item: dict[str, Any] = {
            "path": _normalize_path(path),
            "exists": path.exists(),
        }
        if not path.exists():
            sources.append(item)
            continue
        try:
            raw = path.read_bytes()
            text = raw.decode("utf-8", errors="replace")
            stat = path.stat()
            item.update(
                {
                    "mtime_s": float(stat.st_mtime),
                    "size_bytes": int(stat.st_size),
                    "sha1": hashlib.sha1(raw).hexdigest(),
                    "preview": text[:_OPENCLAW_PREVIEW_CHARS],
                }
            )
            if include_content:
                item["content"] = text[:_OPENCLAW_CONTENT_MAX_CHARS]
        except Exception as exc:
            item["error"] = str(exc)
        sources.append(item)
    return sources


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
    openclaw = data.get("openclaw")
    if not isinstance(openclaw, dict):
        data["openclaw"] = defaults["openclaw"]
        return data
    if not isinstance(openclaw.get("runtime"), dict):
        openclaw["runtime"] = defaults["openclaw"]["runtime"]
    memory = openclaw.get("memory_markdown")
    if not isinstance(memory, dict):
        openclaw["memory_markdown"] = defaults["openclaw"]["memory_markdown"]
    else:
        if not isinstance(memory.get("sources"), list):
            memory["sources"] = []
        if not isinstance(memory.get("loaded_at"), (int, float)):
            memory["loaded_at"] = 0.0
        if not isinstance(memory.get("sync_ok"), bool):
            memory["sync_ok"] = False
    tasks = openclaw.get("tasks")
    if not isinstance(tasks, dict):
        openclaw["tasks"] = defaults["openclaw"]["tasks"]
    else:
        if not isinstance(tasks.get("updated_at"), (int, float)):
            tasks["updated_at"] = 0.0
        if not isinstance(tasks.get("items"), list):
            tasks["items"] = []
    if not isinstance(openclaw.get("ts"), (int, float)):
        openclaw["ts"] = 0.0
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


def update_openclaw_runtime(payload: dict[str, Any]) -> dict[str, Any]:
    now = time.time()
    runtime = dict(payload or {})
    runtime.setdefault("ts", now)
    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked()
            openclaw = data.setdefault("openclaw", _state_defaults()["openclaw"])
            openclaw["runtime"] = runtime
            openclaw["ts"] = now
            data["updated_at"] = now
            _write_unlocked(data)
            return data
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


def _normalize_openclaw_tasks(items: list[dict[str, Any]], now: float) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(items):
        if not isinstance(raw, dict):
            continue
        started_at = raw.get("started_at") or raw.get("created_at") or raw.get("ts")
        updated_at = raw.get("updated_at") or raw.get("finished_at") or started_at or now
        try:
            started_at_f = float(started_at) if started_at is not None else now
        except Exception:
            started_at_f = now
        try:
            updated_at_f = float(updated_at) if updated_at is not None else started_at_f
        except Exception:
            updated_at_f = started_at_f
        task = {
            "id": str(raw.get("id") or raw.get("task_id") or f"task-{index + 1}"),
            "title": str(raw.get("title") or raw.get("name") or raw.get("prompt") or "Task"),
            "status": str(raw.get("status") or raw.get("state") or "unknown"),
            "started_at": started_at_f,
            "updated_at": updated_at_f,
            "duration_s": max(0.0, updated_at_f - started_at_f),
            "result": raw.get("result"),
            "error": raw.get("error"),
        }
        progress = raw.get("progress")
        try:
            if progress is not None:
                task["progress"] = float(progress)
        except Exception:
            pass
        normalized.append(task)
    normalized.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
    return normalized[:64]


def update_openclaw_tasks(payload: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
    now = time.time()
    if isinstance(payload, list):
        raw_items = payload
    else:
        raw_items = payload.get("tasks") or payload.get("items") or []
    if not isinstance(raw_items, list):
        raw_items = []
    tasks_payload = {
        "updated_at": now,
        "items": _normalize_openclaw_tasks(raw_items, now),
    }
    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked()
            openclaw = data.setdefault("openclaw", _state_defaults()["openclaw"])
            openclaw["tasks"] = tasks_payload
            openclaw["ts"] = now
            data["updated_at"] = now
            _write_unlocked(data)
            return openclaw
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def sync_openclaw_memory_once() -> dict[str, Any]:
    now = time.time()
    payload = {
        "loaded_at": now,
        "sync_ok": True,
        "sources": _collect_memory_sources(include_content=False),
    }
    _ensure_parent()
    with LOCK_PATH.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            data = _read_unlocked()
            openclaw = data.setdefault("openclaw", _state_defaults()["openclaw"])
            openclaw["memory_markdown"] = payload
            openclaw["ts"] = now
            data["updated_at"] = now
            _write_unlocked(data)
            return openclaw
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def openclaw_state_snapshot(include_content: bool = False) -> dict[str, Any]:
    data = read_state()
    openclaw = dict(data.get("openclaw", {}) or {})
    if not include_content:
        return openclaw

    memory = dict(openclaw.get("memory_markdown", {}) or {})
    by_path = {
        str(item.get("path")): item
        for item in _collect_memory_sources(include_content=True)
        if isinstance(item, dict)
    }
    merged_sources: list[dict[str, Any]] = []
    for item in memory.get("sources", []) if isinstance(memory.get("sources"), list) else []:
        if not isinstance(item, dict):
            continue
        source_path = str(item.get("path", ""))
        merged = dict(item)
        with_content = by_path.get(source_path)
        if isinstance(with_content, dict) and "content" in with_content:
            merged["content"] = with_content["content"]
        merged_sources.append(merged)
    memory["sources"] = merged_sources
    openclaw["memory_markdown"] = memory
    return openclaw


def write_openclaw_memory(path: str, content: str, append: bool = False) -> dict[str, Any]:
    if not str(path or "").strip():
        raise ValueError("path required")
    target = _resolve_path(path)
    if target.suffix.lower() != ".md":
        raise ValueError("markdown file required")
    if not _path_in_allowed_roots(target):
        raise ValueError("path outside allowed openclaw memory roots")

    text = str(content or "")
    target.parent.mkdir(parents=True, exist_ok=True)
    if append and target.exists():
        with target.open("a", encoding="utf-8") as handle:
            if text and not text.startswith("\n"):
                handle.write("\n")
            handle.write(text)
    else:
        target.write_text(text, encoding="utf-8")

    openclaw = sync_openclaw_memory_once()
    normalized = _normalize_path(target)
    for item in openclaw.get("memory_markdown", {}).get("sources", []):
        if isinstance(item, dict) and str(item.get("path")) == normalized:
            return item
    return {"path": normalized, "exists": target.exists()}


async def openclaw_memory_watch_loop(interval_s: float = 0.5) -> None:
    delay = max(0.25, min(float(interval_s), 5.0))
    while True:
        try:
            await asyncio.to_thread(sync_openclaw_memory_once)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass
        await asyncio.sleep(delay)


def metrics_snapshot() -> dict[str, Any]:
    data = read_state()
    metrics = dict(data.get("metrics", {}) or {})
    workers = data.get("workers", {}) or {}
    if "workers" not in metrics:
        metrics["workers"] = workers
    if "arbitration" not in metrics:
        metrics["arbitration"] = data.get("arbitration", {})
    if "openclaw" not in metrics:
        metrics["openclaw"] = data.get("openclaw", {})
    return metrics


def arbitration_snapshot() -> dict[str, Any]:
    data = read_state()
    payload = data.get("arbitration", {})
    return dict(payload) if isinstance(payload, dict) else {}
