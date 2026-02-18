"""OpenClaw bridge for Didier Flask/FastAPI surfaces."""

from __future__ import annotations

import asyncio
import atexit
import hashlib
import json
import logging
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout
from multiprocessing import Manager
from pathlib import Path
from typing import Any

from core.config import DidierConfig
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
        self._wrapper_restart_interval_s = 8.0
        self._last_wrapper_restart_attempt_s = 0.0
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
        return {"ts": ts, "runtime": runtime, "memory_markdown": memory}

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
        heartbeat_cfg = float(cfg.get("openclaw.heartbeat_interval_seconds", 30))
        self._heartbeat_interval_s = max(2.0, min(heartbeat_cfg, 600.0))
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

    @staticmethod
    def _loop_runner(loop: asyncio.AbstractEventLoop) -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    async def _start_wrapper_task(self) -> None:
        wrapper = self._load_wrapper()
        if not wrapper:
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
                and (now - self._last_wrapper_restart_attempt_s) >= self._wrapper_restart_interval_s
            ):
                self._last_wrapper_restart_attempt_s = now
                try:
                    await wrapper.start()
                except Exception as exc:
                    self._last_heartbeat_ok = False
                    self._last_heartbeat_error = f"openclaw restart failed: {exc}"
                status = wrapper.status()
            if wrapper and (now - self._last_heartbeat_sent_ts) >= self._heartbeat_interval_s:
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
            if now - self._last_memory_refresh_s >= self._memory_refresh_interval_s:
                self._refresh_memory_shared_state()
                self._last_memory_refresh_s = now
            runtime_payload = {
                "ts": now,
                "scheduler_hz": 2.0,
                "tick": tick,
                "heartbeat_interval_s": self._heartbeat_interval_s,
                "last_heartbeat_sent_ts": self._last_heartbeat_sent_ts or None,
                "last_heartbeat_ok": self._last_heartbeat_ok,
                "last_heartbeat_error": self._last_heartbeat_error,
                "status": status,
                "bridge_running": True,
            }
            self._shared_set("runtime", runtime_payload)
            await asyncio.sleep(0.5)

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
                "scheduler_hz": 2.0,
                "tick": 0,
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
                return result
            if time.time() >= boot_deadline:
                return result
            self._ensure_wrapper_running(max_wait_s=1.5)
            time.sleep(0.25)

    def metrics(self, timeout_s: float = 4.0) -> dict[str, Any]:
        if not self.start():
            return {"ok": False, "error": "openclaw disabled or unavailable"}
        if self._loop is None or self._wrapper is None:
            return {"ok": False, "error": "openclaw runtime unavailable"}
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
