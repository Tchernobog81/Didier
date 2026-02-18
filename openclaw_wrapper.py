"""Async OpenClaw process wrapper for Didier.

Step 2 scope:
- start/stop OpenClaw with asyncio.subprocess
- relay prompts via local HTTP hooks
- fetch health metrics from OpenClaw gateway RPC
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import time
from pathlib import Path
from typing import Any
from urllib import error, parse, request


def _dotted_get(data: dict[str, Any], dotted_path: str, default: Any = None) -> Any:
    node: Any = data
    for key in dotted_path.split("."):
        if not isinstance(node, dict) or key not in node:
            return default
        node = node[key]
    return node


def _cfg_get(config: Any, dotted_path: str, default: Any = None) -> Any:
    if hasattr(config, "get"):
        try:
            return config.get(dotted_path, default)
        except TypeError:
            pass
    if isinstance(config, dict):
        return _dotted_get(config, dotted_path, default)
    return default


def _read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        values[key] = value.strip()
    return values


def _extract_json(text: str) -> Any:
    content = (text or "").strip()
    if not content:
        return {}
    try:
        return json.loads(content)
    except Exception:
        pass
    for line in reversed(content.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except Exception:
            continue
    return {"raw": content}


class OpenClawWrapper:
    def __init__(self, config: Any, base_dir: str | Path = ".") -> None:
        self._config = config
        self._base_dir = Path(base_dir).resolve()
        self._process: asyncio.subprocess.Process | None = None
        self._started_at_monotonic = 0.0
        self._precompile_running = False
        self._last_precompile_at = 0.0
        self._last_precompile_ok: bool | None = None
        self._last_precompile_error = ""

        self.repo_path = (self._base_dir / str(_cfg_get(config, "openclaw.repo_path", "openclaw"))).resolve()
        self.env_file = (self._base_dir / str(_cfg_get(config, "openclaw.env_file", "config/openclaw.env"))).resolve()
        self.gateway_url = str(_cfg_get(config, "openclaw.gateway_url", "http://127.0.0.1:3800")).rstrip("/")
        self.hooks_base_path = str(_cfg_get(config, "openclaw.hooks_base_path", "/hooks")).strip() or "/hooks"
        if not self.hooks_base_path.startswith("/"):
            self.hooks_base_path = "/" + self.hooks_base_path
        self.gateway_token_env = str(
            _cfg_get(config, "openclaw.gateway_token_env", "OPENCLAW_GATEWAY_TOKEN")
        ).strip() or "OPENCLAW_GATEWAY_TOKEN"
        self.pnpm_cmd = str(_cfg_get(config, "openclaw.pnpm_cmd", "pnpm")).strip() or "pnpm"
        self.gateway_ws_url = str(_cfg_get(config, "openclaw.gateway_ws_url", "")).strip()
        self._start_cmd = _cfg_get(config, "openclaw.start_cmd", None)
        self.prefer_compiled_aot = bool(_cfg_get(config, "openclaw.prefer_compiled_aot", True))
        self.compiled_entrypoint = str(
            _cfg_get(config, "openclaw.compiled_entrypoint", "dist/index.js")
        ).strip() or "dist/index.js"
        self.precompile_on_start = bool(_cfg_get(config, "openclaw.precompile_on_start", False))
        precompile_cfg = _cfg_get(config, "openclaw.precompile_cmd", None)
        if isinstance(precompile_cfg, list) and precompile_cfg:
            self.precompile_cmd = [str(part) for part in precompile_cfg]
        else:
            self.precompile_cmd = [self.pnpm_cmd, "build"]
        self.precompile_timeout_s = float(_cfg_get(config, "openclaw.precompile_timeout_s", 180))
        self.precompile_timeout_s = max(15.0, min(self.precompile_timeout_s, 900.0))

    def _runtime_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.update(_read_env_file(self.env_file))
        return env

    def _resolve_ws_url(self) -> str:
        if self.gateway_ws_url:
            return self.gateway_ws_url
        parsed = parse.urlparse(self.gateway_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 3800
        return f"{scheme}://{host}:{port}"

    def _resolve_port(self) -> int:
        parsed = parse.urlparse(self.gateway_url)
        return parsed.port or 3800

    def _resolve_host(self) -> str:
        parsed = parse.urlparse(self.gateway_url)
        return parsed.hostname or "127.0.0.1"

    def _compiled_entrypoint_path(self) -> Path:
        entry = Path(self.compiled_entrypoint)
        if not entry.is_absolute():
            entry = self.repo_path / entry
        return entry

    def _compiled_available(self) -> bool:
        return self._compiled_entrypoint_path().exists()

    def compiled_available(self) -> bool:
        return self._compiled_available()

    def _start_mode(self) -> str:
        if isinstance(self._start_cmd, list) and self._start_cmd:
            return "custom"
        if self.prefer_compiled_aot and self._compiled_available():
            return "compiled"
        return "tsx"

    def _resolve_start_cmd(self) -> list[str]:
        if isinstance(self._start_cmd, list) and self._start_cmd:
            return [str(part) for part in self._start_cmd]
        if self.prefer_compiled_aot and self._compiled_available():
            return [
                "node",
                str(self._compiled_entrypoint_path()),
                "gateway",
                "run",
                "--port",
                str(self._resolve_port()),
            ]
        return [
            self.pnpm_cmd,
            "openclaw",
            "gateway",
            "run",
            "--port",
            str(self._resolve_port()),
        ]

    def _hooks_url(self, suffix: str) -> str:
        base = f"{self.gateway_url}{self.hooks_base_path}".rstrip("/")
        return f"{base}/{suffix.lstrip('/')}"

    def _auth_headers(self, env: dict[str, str]) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = env.get(self.gateway_token_env, "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def status(self) -> dict[str, Any]:
        running = bool(self._process and self._process.returncode is None)
        if not running:
            running = self._gateway_reachable_sync(timeout_s=0.2)
        uptime_s = 0.0
        if running and self._started_at_monotonic > 0:
            uptime_s = max(0.0, time.monotonic() - self._started_at_monotonic)
        return {
            "running": running,
            "pid": self._process.pid if self._process else None,
            "uptime_s": round(uptime_s, 2),
            "repo_path": str(self.repo_path),
            "gateway_url": self.gateway_url,
            "hooks_base_path": self.hooks_base_path,
            "gateway_ws_url": self._resolve_ws_url(),
            "start_mode": self._start_mode(),
            "compiled_available": self._compiled_available(),
            "compiled_entrypoint": str(self._compiled_entrypoint_path()),
            "precompile_on_start": self.precompile_on_start,
            "precompile_running": self._precompile_running,
            "last_precompile_at": self._last_precompile_at or None,
            "last_precompile_ok": self._last_precompile_ok,
            "last_precompile_error": self._last_precompile_error,
        }

    async def precompile(self) -> dict[str, Any]:
        if self._precompile_running:
            return {"ok": True, "status": "already-running", "wrapper": self.status()}
        self._precompile_running = True
        env = self._runtime_env()
        cmd = list(self.precompile_cmd)
        started = time.time()
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.repo_path),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=max(1.0, self.precompile_timeout_s)
            )
            stdout_text = out.decode("utf-8", errors="replace")
            stderr_text = err.decode("utf-8", errors="replace")
            ok = proc.returncode == 0
            self._last_precompile_ok = ok
            self._last_precompile_error = "" if ok else (stderr_text.strip() or stdout_text.strip())
            return {
                "ok": ok,
                "command": cmd,
                "returncode": proc.returncode,
                "elapsed_s": round(time.time() - started, 2),
                "stdout": stdout_text[-2000:],
                "stderr": stderr_text[-2000:],
                "wrapper": self.status(),
            }
        except asyncio.TimeoutError:
            self._last_precompile_ok = False
            self._last_precompile_error = "precompile timeout"
            return {
                "ok": False,
                "command": cmd,
                "error": "precompile timeout",
                "elapsed_s": round(time.time() - started, 2),
                "wrapper": self.status(),
            }
        except Exception as exc:
            self._last_precompile_ok = False
            self._last_precompile_error = str(exc)
            return {
                "ok": False,
                "command": cmd,
                "error": str(exc),
                "elapsed_s": round(time.time() - started, 2),
                "wrapper": self.status(),
            }
        finally:
            self._precompile_running = False
            self._last_precompile_at = time.time()

    async def start(self) -> dict[str, Any]:
        if self._gateway_reachable_sync(timeout_s=0.35):
            if self._started_at_monotonic <= 0:
                self._started_at_monotonic = time.monotonic()
            return self.status()
        if self._process and self._process.returncode is None:
            return self.status()
        if not self.repo_path.exists():
            raise FileNotFoundError(f"OpenClaw repo not found: {self.repo_path}")
        env = self._runtime_env()
        cmd = self._resolve_start_cmd()
        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.repo_path),
            env=env,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        self._started_at_monotonic = time.monotonic()
        return self.status()

    async def stop(self, timeout_s: float = 8.0) -> dict[str, Any]:
        if not self._process:
            return self.status()
        if self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=max(1.0, timeout_s))
            except asyncio.TimeoutError:
                self._process.kill()
                await self._process.wait()
        return self.status()

    async def relay_prompt(
        self,
        prompt: str,
        *,
        agent_id: str | None = None,
        session_key: str | None = None,
        wake_mode: str = "now",
        timeout_s: float = 4.0,
    ) -> dict[str, Any]:
        message = str(prompt or "").strip()
        if not message:
            return {"ok": False, "error": "prompt required"}
        payload: dict[str, Any] = {
            "message": message,
            "name": "Didier",
            "wakeMode": "next-heartbeat" if wake_mode == "next-heartbeat" else "now",
            "deliver": False,
        }
        if agent_id:
            payload["agentId"] = str(agent_id).strip()
        if session_key:
            payload["sessionKey"] = str(session_key).strip()
        return await self._post_json(self._hooks_url("agent"), payload, timeout_s=timeout_s)

    async def relay_wake(self, text: str, timeout_s: float = 3.0) -> dict[str, Any]:
        wake_text = str(text or "").strip()
        if not wake_text:
            return {"ok": False, "error": "text required"}
        payload = {"text": wake_text, "mode": "now"}
        return await self._post_json(self._hooks_url("wake"), payload, timeout_s=timeout_s)

    async def fetch_metrics(self, timeout_s: float = 5.0) -> dict[str, Any]:
        env = self._runtime_env()
        if self.prefer_compiled_aot and self._compiled_available():
            cmd = [
                "node",
                str(self._compiled_entrypoint_path()),
                "gateway",
                "call",
                "health",
                "--json",
                "--url",
                self._resolve_ws_url(),
            ]
        else:
            cmd = [
                self.pnpm_cmd,
                "openclaw",
                "gateway",
                "call",
                "health",
                "--json",
                "--url",
                self._resolve_ws_url(),
            ]
        token = env.get(self.gateway_token_env, "").strip()
        if token:
            cmd.extend(["--token", token])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(self.repo_path),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=max(1.0, timeout_s + 1.0)
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "ok": False,
                "error": "openclaw metrics timeout",
                "status": self.status(),
            }
        stdout_text = out.decode("utf-8", errors="replace")
        stderr_text = err.decode("utf-8", errors="replace").strip()
        if proc.returncode != 0:
            return {
                "ok": False,
                "error": "openclaw metrics command failed",
                "returncode": proc.returncode,
                "stderr": stderr_text,
                "status": self.status(),
            }
        return {
            "ok": True,
            "health": _extract_json(stdout_text),
            "stderr": stderr_text,
            "status": self.status(),
        }

    async def _post_json(self, url: str, payload: dict[str, Any], timeout_s: float) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        env = self._runtime_env()
        headers = self._auth_headers(env)

        def _send() -> dict[str, Any]:
            req = request.Request(url=url, data=body, headers=headers, method="POST")
            try:
                with request.urlopen(req, timeout=max(0.2, float(timeout_s))) as resp:
                    text = resp.read().decode("utf-8", errors="replace")
                    return {
                        "ok": 200 <= int(resp.status) < 300,
                        "status_code": int(resp.status),
                        "url": url,
                        "data": _extract_json(text),
                    }
            except error.HTTPError as exc:
                raw = exc.read().decode("utf-8", errors="replace")
                return {
                    "ok": False,
                    "status_code": int(exc.code),
                    "url": url,
                    "error": _extract_json(raw),
                }
            except Exception as exc:
                return {
                    "ok": False,
                    "status_code": None,
                    "url": url,
                    "error": str(exc),
                }

        return await asyncio.to_thread(_send)

    async def wait_ready(self, timeout_s: float = 6.0) -> bool:
        host = self._resolve_host()
        port = self._resolve_port()
        deadline = time.monotonic() + max(0.5, float(timeout_s))
        while time.monotonic() < deadline:
            if self._gateway_reachable_sync(timeout_s=0.25):
                return True
            if self._process and self._process.returncode is not None:
                return False
            if await asyncio.to_thread(self._probe_tcp, host, port, 0.35):
                return True
            await asyncio.sleep(0.2)
        return False

    @staticmethod
    def _probe_tcp(host: str, port: int, timeout_s: float) -> bool:
        try:
            with socket.create_connection((host, int(port)), timeout=float(timeout_s)):
                return True
        except Exception:
            return False

    def _gateway_reachable_sync(self, timeout_s: float = 0.35) -> bool:
        return self._probe_tcp(self._resolve_host(), self._resolve_port(), timeout_s)
