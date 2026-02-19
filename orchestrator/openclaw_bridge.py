"""OpenClaw bridge for Didier Flask/FastAPI surfaces."""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import logging
import os
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout
from multiprocessing import Manager
from pathlib import Path
from typing import Any

from core.config import DidierConfig
from core.shared_state import metrics_snapshot as didier_metrics_snapshot
from core.shared_state import update_openclaw_tasks
from openclaw_wrapper import OpenClawWrapper

_LOG = logging.getLogger("didier.openclaw")


class OpenClawBridge:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._wrapper: OpenClawWrapper | None = None
        self._config: DidierConfig | None = None
        self._enabled = False
        self._shutdown_registered = False
        self._heartbeat_task: asyncio.Task | None = None
        self._heartbeat_interval_s = 30.0
        self._scheduler_hz = 2.0
        self._scheduler_interval_s = 0.5
        self._wrapper_restart_interval_s = 8.0
        self._wrapper_heartbeat_enabled = True
        self._didier_state_sync_enabled = True
        self._last_wrapper_restart_attempt_s = 0.0
        self._native_only = str(os.getenv("DIDIER_OPENCLAW_NATIVE_ONLY", "0")).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._last_memory_refresh_s = 0.0
        self._memory_refresh_interval_s = 60.0
        self._memory_preview_chars = 300
        self._memory_file_cache: dict[str, dict[str, Any]] = {}
        self._last_heartbeat_sent_ts = 0.0
        self._last_heartbeat_ok: bool | None = None
        self._last_heartbeat_error = ""
        self._base_dir = Path(".").resolve()
        self._shared_state_manager: Any = None
        try:
            self._shared_state_manager = Manager()
            self._shared_state: Any = self._shared_state_manager.dict()
        except Exception:
            self._shared_state = {}
        self._shared_set("runtime", {"status": "idle", "scheduler_hz": 2.0, "tick": 0})
        self._shared_set("memory_markdown", {"loaded_at": 0.0, "sources": []})
        self._shared_set("didier_state", {"ts": 0.0, "source": "shared_state_v1"})
        self._shared_set("tasks", {"updated_at": 0.0, "items": []})

    def _clone_jsonable(self, value: Any) -> Any:
        try:
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))
        except Exception:
            return value

    def _shared_set(self, key: str, value: Any) -> None:
        with self._lock:
            self._shared_state[key] = value
            self._shared_state["ts"] = time.time()

    def shared_state_snapshot(self) -> dict[str, Any]:
        with self._lock:
            ts = float(self._shared_state.get("ts", 0.0))
            runtime = self._clone_jsonable(self._shared_state.get("runtime", {}))
            memory = self._clone_jsonable(self._shared_state.get("memory_markdown", {}))
            didier_state = self._clone_jsonable(self._shared_state.get("didier_state", {}))
            tasks = self._clone_jsonable(self._shared_state.get("tasks", {"updated_at": 0.0, "items": []}))
        return {
            "ts": ts,
            "runtime": runtime,
            "memory_markdown": memory,
            "didier_state": didier_state,
            "tasks": tasks,
        }

    @staticmethod
    def _task_ts(value: Any, fallback: float) -> float:
        try:
            ts = float(value)
            if ts <= 0:
                return fallback
            return ts
        except Exception:
            return fallback

    def _normalize_tasks(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        now = time.time()
        normalized: list[dict[str, Any]] = []
        for idx, raw in enumerate(items):
            if not isinstance(raw, dict):
                continue
            started_at = self._task_ts(raw.get("started_at"), now)
            updated_at = self._task_ts(raw.get("updated_at"), started_at)
            task: dict[str, Any] = {
                "id": str(raw.get("id") or f"oc-{idx + 1}"),
                "title": str(raw.get("title") or raw.get("prompt") or "OpenClaw task"),
                "status": str(raw.get("status") or "unknown"),
                "started_at": started_at,
                "updated_at": updated_at,
                "duration_s": max(0.0, updated_at - started_at),
                "result": raw.get("result"),
                "error": raw.get("error"),
            }
            if "progress" in raw:
                try:
                    task["progress"] = float(raw.get("progress"))
                except Exception:
                    pass
            normalized.append(task)
        normalized.sort(key=lambda item: float(item.get("updated_at", 0.0)), reverse=True)
        return normalized[:64]

    def _current_tasks(self) -> list[dict[str, Any]]:
        with self._lock:
            block = self._shared_state.get("tasks", {"updated_at": 0.0, "items": []})
            if isinstance(block, dict):
                raw_items = block.get("items", [])
            else:
                raw_items = []
            return self._clone_jsonable(raw_items if isinstance(raw_items, list) else [])

    def _publish_tasks(self, tasks: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {"updated_at": time.time(), "items": self._normalize_tasks(tasks)}
        self._shared_set("tasks", payload)
        try:
            update_openclaw_tasks(payload)
        except Exception:
            pass
        return payload

    def _start_task(self, prompt: str) -> str:
        now = time.time()
        task_id = f"oc-{int(now * 1000)}"
        tasks = self._current_tasks()
        tasks.append(
            {
                "id": task_id,
                "title": str(prompt or "").strip()[:120] or "OpenClaw task",
                "status": "running",
                "started_at": now,
                "updated_at": now,
                "duration_s": 0.0,
                "result": None,
                "error": None,
            }
        )
        self._publish_tasks(tasks)
        return task_id

    def _finish_task(self, task_id: str, result: dict[str, Any]) -> None:
        now = time.time()
        rid = str(task_id or "").strip()
        tasks = self._current_tasks()
        matched = False
        for task in tasks:
            if str(task.get("id", "")) != rid:
                continue
            matched = True
            task["updated_at"] = now
            started_at = self._task_ts(task.get("started_at"), now)
            task["duration_s"] = max(0.0, now - started_at)
            ok = bool((result or {}).get("ok", False))
            task["status"] = "done" if ok else "error"
            if "result" in result:
                task["result"] = result.get("result")
            elif "data" in result:
                task["result"] = result.get("data")
            elif ok:
                task["result"] = "ok"
            task["error"] = result.get("error")
            break
        if not matched:
            tasks.append(
                {
                    "id": rid or f"oc-{int(now * 1000)}",
                    "title": "OpenClaw task",
                    "status": "done" if bool((result or {}).get("ok", False)) else "error",
                    "started_at": now,
                    "updated_at": now,
                    "duration_s": 0.0,
                    "result": result.get("result") if isinstance(result, dict) else None,
                    "error": result.get("error") if isinstance(result, dict) else "unknown error",
                }
            )
        self._publish_tasks(tasks)

    def tasks(self) -> dict[str, Any]:
        with self._lock:
            block = self._clone_jsonable(self._shared_state.get("tasks", {"updated_at": 0.0, "items": []}))
        if not isinstance(block, dict):
            block = {"updated_at": 0.0, "items": []}
        items = block.get("items", [])
        return {
            "ok": True,
            "ts": time.time(),
            "tasks": self._normalize_tasks(items if isinstance(items, list) else []),
            "shared_state": self.shared_state_snapshot(),
        }

    @staticmethod
    def _to_bool(value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def _load_runtime_config(self, cfg: DidierConfig | None) -> dict[str, Any]:
        runtime_path = str(os.getenv("OPENCLAW_CONFIG_PATH", "")).strip()
        if not runtime_path and cfg:
            runtime_path = str(cfg.get("openclaw.runtime_config_path", "") or "").strip()
        if not runtime_path:
            runtime_path = "config/openclaw.runtime.json"
        path = Path(runtime_path)
        if not path.is_absolute():
            path = self._base_dir / path
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def _load_wrapper(self) -> OpenClawWrapper | None:
        if self._wrapper is not None:
            return self._wrapper
        try:
            cfg = DidierConfig.load("config/config.json")
        except Exception as exc:
            _LOG.warning("OpenClaw bridge config load failed: %s", exc)
            return None
        self._config = cfg
        self._enabled = bool(cfg.get("openclaw.enabled", False))
        if bool(cfg.get("openclaw.native_enabled", False)):
            self._native_only = True
        runtime_cfg = self._load_runtime_config(cfg)
        didier_runtime_cfg = (
            runtime_cfg.get("didier", {}) if isinstance(runtime_cfg.get("didier", {}), dict) else {}
        )
        scheduler_hz_cfg = float(
            cfg.get(
                "openclaw.scheduler_hz",
                didier_runtime_cfg.get("heartbeat_hz", 2.0),
            )
        )
        self._scheduler_hz = max(0.5, min(scheduler_hz_cfg, 10.0))
        self._scheduler_interval_s = 1.0 / self._scheduler_hz
        heartbeat_cfg = float(cfg.get("openclaw.heartbeat_interval_seconds", 30))
        self._heartbeat_interval_s = max(0.5, min(heartbeat_cfg, 600.0))
        self._wrapper_heartbeat_enabled = self._to_bool(
            cfg.get(
                "openclaw.wrapper_heartbeat_enabled",
                didier_runtime_cfg.get("wrapper_heartbeat_enabled", not self._native_only),
            ),
            default=not self._native_only,
        )
        self._didier_state_sync_enabled = self._to_bool(
            cfg.get(
                "openclaw.didier_state_sync_enabled",
                didier_runtime_cfg.get("shared_state_sync", True),
            ),
            default=True,
        )
        restart_cfg = float(cfg.get("openclaw.restart_interval_seconds", 8))
        self._wrapper_restart_interval_s = max(2.0, min(restart_cfg, 120.0))
        memory_refresh_cfg = float(cfg.get("openclaw.memory_refresh_seconds", 60))
        self._memory_refresh_interval_s = max(10.0, min(memory_refresh_cfg, 3600.0))
        memory_preview_cfg = int(cfg.get("openclaw.memory_preview_chars", 300))
        self._memory_preview_chars = max(80, min(memory_preview_cfg, 1200))
        if not self._enabled:
            return None
        self._wrapper = OpenClawWrapper(cfg)
        self._refresh_memory_shared_state()
        return self._wrapper

    def _memory_source_paths(self) -> list[Path]:
        cfg = self._config
        raw_sources = cfg.get("openclaw.memory_markdown_files", None) if cfg else None
        if not isinstance(raw_sources, list) or not raw_sources:
            raw_sources = ["openclaw/AGENTS.md"]
        paths: list[Path] = []
        for item in raw_sources:
            value = str(item or "").strip()
            if not value:
                continue
            path = Path(value)
            if not path.is_absolute():
                path = self._base_dir / path
            paths.append(path)
        return paths

    def _refresh_memory_shared_state(self) -> dict[str, Any]:
        sources: list[dict[str, Any]] = []
        for path in self._memory_source_paths():
            item: dict[str, Any] = {"path": str(path), "exists": path.exists()}
            if path.exists():
                try:
                    stat = path.stat()
                    cache_key = str(path)
                    cached = self._memory_file_cache.get(cache_key, {})
                    mtime_s = float(stat.st_mtime)
                    size_bytes = int(stat.st_size)
                    if (
                        cached
                        and float(cached.get("mtime_s", -1)) == mtime_s
                        and int(cached.get("size_bytes", -1)) == size_bytes
                    ):
                        sha1 = str(cached.get("sha1", ""))
                        preview = str(cached.get("preview", ""))
                    else:
                        raw = path.read_bytes()
                        text = raw.decode("utf-8", errors="replace")
                        sha1 = hashlib.sha1(raw).hexdigest()
                        preview = text[: self._memory_preview_chars]
                        self._memory_file_cache[cache_key] = {
                            "mtime_s": mtime_s,
                            "size_bytes": size_bytes,
                            "sha1": sha1,
                            "preview": preview,
                        }
                    item.update(
                        {
                            "mtime_s": mtime_s,
                            "size_bytes": size_bytes,
                            "sha1": sha1,
                            "preview": preview,
                        }
                    )
                except Exception as exc:
                    item["error"] = str(exc)
            sources.append(item)
        payload = {"loaded_at": time.time(), "sources": sources}
        self._shared_set("memory_markdown", payload)
        return payload

    def _sync_didier_state(self) -> dict[str, Any]:
        snapshot = didier_metrics_snapshot()
        workers = snapshot.get("workers", {}) if isinstance(snapshot.get("workers"), dict) else {}
        payload = {
            "ts": time.time(),
            "source": str(snapshot.get("source", "shared_state_v1")),
            "cpu": snapshot.get("cpu", {}),
            "memory": snapshot.get("memory", {}),
            "npu": snapshot.get("npu", {}),
            "asr": snapshot.get("asr", {}),
            "vision": workers.get("vision", {}),
            "audio": workers.get("audio", {}),
            "brain": workers.get("brain", {}),
            "workers": workers,
        }
        self._shared_set("didier_state", payload)
        return payload

    @staticmethod
    def _loop_runner(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    async def _start_wrapper_task(self) -> None:
        wrapper = self._load_wrapper()
        if not wrapper:
            return
        if self._native_only:
            return
        if wrapper.precompile_on_start and not wrapper.compiled_available():
            # Best effort AOT precompile; do not block API startup.
            asyncio.create_task(wrapper.precompile())
        try:
            await wrapper.start()
        except Exception as exc:
            _LOG.warning("OpenClaw start failed: %s", exc)

    async def _heartbeat_scheduler(self) -> None:
        tick = 0
        while True:
            tick += 1
            now = time.time()
            wrapper = self._wrapper
            status = wrapper.status() if wrapper else {"enabled": self._enabled, "running": False}
            if (
                wrapper
                and not bool(status.get("running"))
                and not self._native_only
                and (now - self._last_wrapper_restart_attempt_s) >= self._wrapper_restart_interval_s
            ):
                self._last_wrapper_restart_attempt_s = now
                try:
                    await wrapper.start()
                except Exception as exc:
                    self._last_heartbeat_ok = False
                    self._last_heartbeat_error = f"openclaw restart failed: {exc}"
                status = wrapper.status()
            if (
                self._wrapper_heartbeat_enabled
                and wrapper
                and (now - self._last_heartbeat_sent_ts) >= self._heartbeat_interval_s
            ):
                self._last_heartbeat_sent_ts = now
                try:
                    hb = await wrapper.fetch_metrics(timeout_s=1.5)
                    self._last_heartbeat_ok = bool(hb.get("ok", False))
                    self._last_heartbeat_error = (
                        str(hb.get("error", "")).strip() if not self._last_heartbeat_ok else ""
                    )
                except Exception as exc:
                    self._last_heartbeat_ok = False
                    self._last_heartbeat_error = str(exc)
            if self._didier_state_sync_enabled:
                try:
                    self._sync_didier_state()
                except Exception as exc:
                    self._last_heartbeat_error = f"didier_state_sync_failed: {exc}"
            if now - self._last_memory_refresh_s >= self._memory_refresh_interval_s:
                self._refresh_memory_shared_state()
                self._last_memory_refresh_s = now
            runtime_payload = {
                "ts": now,
                "scheduler_hz": self._scheduler_hz,
                "tick": tick,
                "wrapper_heartbeat_enabled": self._wrapper_heartbeat_enabled,
                "didier_state_sync_enabled": self._didier_state_sync_enabled,
                "heartbeat_interval_s": self._heartbeat_interval_s,
                "last_heartbeat_sent_ts": self._last_heartbeat_sent_ts or None,
                "last_heartbeat_ok": self._last_heartbeat_ok,
                "last_heartbeat_error": self._last_heartbeat_error,
                "status": status,
                "bridge_running": True,
            }
            self._shared_set("runtime", runtime_payload)
            await asyncio.sleep(self._scheduler_interval_s)

    async def _start_runtime(self) -> None:
        if self._heartbeat_task is None or self._heartbeat_task.done():
            self._heartbeat_task = asyncio.create_task(self._heartbeat_scheduler())
        asyncio.create_task(self._start_wrapper_task())

    async def _stop_runtime_task(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except Exception:
                pass
            self._heartbeat_task = None
        if self._wrapper is not None:
            try:
                await self._wrapper.stop()
            except Exception:
                pass
        status = self._wrapper.status() if self._wrapper else {"enabled": self._enabled, "running": False}
        self._shared_set(
            "runtime",
            {
                "ts": time.time(),
                "scheduler_hz": self._scheduler_hz,
                "tick": 0,
                "wrapper_heartbeat_enabled": self._wrapper_heartbeat_enabled,
                "didier_state_sync_enabled": self._didier_state_sync_enabled,
                "heartbeat_interval_s": self._heartbeat_interval_s,
                "last_heartbeat_sent_ts": self._last_heartbeat_sent_ts or None,
                "last_heartbeat_ok": self._last_heartbeat_ok,
                "last_heartbeat_error": self._last_heartbeat_error,
                "status": status,
                "bridge_running": False,
            },
        )

    def start(self) -> bool:
        wrapper = self._load_wrapper()
        if not wrapper:
            return False
        with self._lock:
            if self._loop is None:
                self._loop = asyncio.new_event_loop()
                self._thread = threading.Thread(
                    target=self._loop_runner,
                    args=(self._loop,),
                    daemon=True,
                    name="openclaw-bridge-loop",
                )
                self._thread.start()
            if not self._shutdown_registered:
                atexit.register(self.stop)
                self._shutdown_registered = True
            fut = asyncio.run_coroutine_threadsafe(self._start_runtime(), self._loop)
        try:
            fut.result(timeout=2.0)
        except Exception:
            pass
        return True

    def stop(self) -> None:
        with self._lock:
            loop = self._loop
            thread = self._thread
            self._loop = None
            self._thread = None
        if loop is None:
            return
        fut = None
        try:
            fut = asyncio.run_coroutine_threadsafe(self._stop_runtime_task(), loop)
            fut.result(timeout=12.0)
        except Exception:
            if fut is not None:
                fut.cancel()
        try:
            loop.call_soon_threadsafe(loop.stop)
        except Exception:
            pass
        if thread is not None:
            try:
                thread.join(timeout=1.5)
            except Exception:
                pass

    def status(self) -> dict[str, Any]:
        wrapper = self._wrapper or self._load_wrapper()
        loop_running = bool(self._loop is not None and self._thread and self._thread.is_alive())
        if wrapper is None:
            return {"enabled": self._enabled, "running": False, "bridge_running": loop_running}
        data = wrapper.status()
        data["enabled"] = self._enabled
        data["bridge_running"] = loop_running
        data["shared_state"] = self.shared_state_snapshot()
        return data

    def relay_prompt(
        self,
        prompt: str,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        wake_mode: str = "now",
        timeout_s: float = 3.0,
    ) -> dict[str, Any]:
        if not self.start():
            return {"ok": False, "error": "openclaw disabled or unavailable"}
        if self._loop is None or self._wrapper is None:
            return {"ok": False, "error": "openclaw runtime unavailable"}
        task_id = self._start_task(prompt)
        if not self._native_only:
            self._ensure_wrapper_running(max_wait_s=max(1.0, min(timeout_s, 8.0)))
        boot_deadline = time.time() + max(2.0, min(12.0, timeout_s + 6.0))
        while True:
            fut = asyncio.run_coroutine_threadsafe(
                self._wrapper.relay_prompt(
                    prompt,
                    agent_id=agent_id,
                    session_key=session_key,
                    wake_mode=wake_mode,
                    timeout_s=timeout_s,
                ),
                self._loop,
            )
            try:
                result = fut.result(timeout=max(1.0, timeout_s + 1.0))
            except FutureTimeout:
                fut.cancel()
                result = {"ok": False, "error": "openclaw relay timeout"}
            except Exception as exc:
                fut.cancel()
                result = {"ok": False, "error": f"openclaw relay failed: {exc}"}
            err = str(result.get("error", "")).lower()
            if "connection refused" not in err:
                self._finish_task(task_id, result if isinstance(result, dict) else {"ok": False})
                return result
            if time.time() >= boot_deadline:
                self._finish_task(task_id, result if isinstance(result, dict) else {"ok": False})
                return result
            if not self._native_only:
                self._ensure_wrapper_running(max_wait_s=1.5)
            time.sleep(0.25)

    def metrics(self, timeout_s: float = 4.0) -> dict[str, Any]:
        if not self.start():
            return {"ok": False, "error": "openclaw disabled or unavailable"}
        if self._loop is None or self._wrapper is None:
            return {"ok": False, "error": "openclaw runtime unavailable"}
        if self._native_only:
            status = self._wrapper.status()
            result = {
                "ok": bool(status.get("running", False)),
                "native": True,
                "status": status,
                "source": "openclaw_native_bridge",
            }
            if not result["ok"]:
                result["error"] = "openclaw native runtime unavailable"
            result["shared_state"] = self.shared_state_snapshot()
            return result
        if not self._native_only:
            self._ensure_wrapper_running(max_wait_s=max(1.0, min(timeout_s, 10.0)))
        fut = asyncio.run_coroutine_threadsafe(
            self._wrapper.fetch_metrics(timeout_s=timeout_s),
            self._loop,
        )
        try:
            result = fut.result(timeout=max(1.0, timeout_s + 1.0))
        except FutureTimeout:
            fut.cancel()
            result = {"ok": False, "error": "openclaw metrics timeout"}
        except Exception as exc:
            fut.cancel()
            result = {"ok": False, "error": f"openclaw metrics failed: {exc}"}
        result["shared_state"] = self.shared_state_snapshot()
        return result

    def _ensure_wrapper_running(self, max_wait_s: float = 6.0) -> bool:
        if self._loop is None or self._wrapper is None:
            return False
        if self._native_only:
            try:
                return bool(self._wrapper.status().get("running"))
            except Exception:
                return False
        deadline = time.time() + max(0.5, max_wait_s)
        while time.time() < deadline:
            status = self._wrapper.status()
            if bool(status.get("running")):
                try:
                    remaining = max(0.5, deadline - time.time())
                    fut_ready = asyncio.run_coroutine_threadsafe(
                        self._wrapper.wait_ready(timeout_s=min(remaining, 3.0)),
                        self._loop,
                    )
                    if bool(fut_ready.result(timeout=min(4.0, remaining + 0.5))):
                        return True
                except Exception:
                    pass
            fut = asyncio.run_coroutine_threadsafe(self._wrapper.start(), self._loop)
            try:
                fut.result(timeout=2.0)
            except Exception:
                fut.cancel()
            time.sleep(0.25)
        try:
            return bool(self._wrapper.status().get("running"))
        except Exception:
            return False


_OPENCLAW_BRIDGE = OpenClawBridge()


def get_openclaw_bridge() -> OpenClawBridge:
    return _OPENCLAW_BRIDGE


def build_openclaw_blueprint() -> Any:
    try:
        from flask import Blueprint, jsonify, request
    except Exception as exc:  # pragma: no cover - Flask optional in FastAPI runtime
        raise RuntimeError("Flask is required to build OpenClaw blueprint") from exc
    bp = Blueprint("openclaw_agent_bridge", __name__)

    @bp.post("/agent/react")
    def agent_react() -> Any:
        payload = request.get_json(silent=True) or {}
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            return jsonify({"ok": False, "error": "prompt required"}), 400
        timeout_s = float(payload.get("timeout_s", 3.0))
        timeout_s = max(0.5, min(timeout_s, 10.0))
        result = _OPENCLAW_BRIDGE.relay_prompt(
            prompt,
            agent_id=str(payload.get("agent_id", "")).strip() or None,
            session_key=str(payload.get("session_key", "")).strip() or None,
            wake_mode=str(payload.get("wake_mode", "now")).strip() or "now",
            timeout_s=timeout_s,
        )
        code = int(result.get("status_code") or (202 if result.get("ok") else 503))
        return jsonify(result), code

    @bp.get("/agent/metrics")
    def agent_metrics() -> Any:
        timeout_s = float(request.args.get("timeout_s", 4.0))
        timeout_s = max(0.5, min(timeout_s, 12.0))
        result = _OPENCLAW_BRIDGE.metrics(timeout_s=timeout_s)
        return jsonify(result), (200 if result.get("ok") else 503)

    @bp.get("/agent/tasks")
    def agent_tasks() -> Any:
        return jsonify(_OPENCLAW_BRIDGE.tasks()), 200

    @bp.get("/agent/status")
    def agent_status() -> Any:
        return jsonify(_OPENCLAW_BRIDGE.status()), 200

    @bp.get("/agent/shared-state")
    def agent_shared_state() -> Any:
        return jsonify(_OPENCLAW_BRIDGE.shared_state_snapshot()), 200

    return bp


def register_openclaw_blueprint(app: Any) -> None:
    name = "openclaw_agent_bridge"
    if getattr(app, "blueprints", None) and name in app.blueprints:
        return
    app.register_blueprint(build_openclaw_blueprint())
