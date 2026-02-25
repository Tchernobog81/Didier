"""Didier Picobot HTTP bridge (local compatibility layer on :3901).

This service exposes the /agent/* contract expected by Didier API and routes
react requests to the Picobot container CLI.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from fastapi import FastAPI
from fastapi import HTTPException
import uvicorn

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_ROUTING_IMPORT_ERROR = ""
try:
    from core.backend_routing import choose_backend as choose_backend_contract
except Exception as exc:
    choose_backend_contract = None
    _ROUTING_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

APP_TITLE = "Didier Picobot Bridge"
DEFAULT_TIMEOUT_S = 2.0
REACT_TIMEOUT_MAX_S = 6.0
DEFAULT_REACT_TIMEOUT_S = 5.0
try:
    _env_react_timeout = float(
        os.getenv("DIDIER_PICOBOT_REACT_TIMEOUT_S", str(DEFAULT_REACT_TIMEOUT_S))
    )
except Exception:
    _env_react_timeout = DEFAULT_REACT_TIMEOUT_S
REACT_TIMEOUT_DEFAULT_S = max(0.2, min(_env_react_timeout, REACT_TIMEOUT_MAX_S))
PICOBOT_CONTAINER = os.getenv("DIDIER_PICOBOT_CONTAINER", "didier-picobot").strip() or "didier-picobot"
PICOBOT_DATA_DIR = Path(os.getenv("DIDIER_PICOBOT_DATA_DIR", "picobot_data")).resolve()
PICOBOT_EXPECTED_BUILTIN_TOOLS = (
    "CreateSkill",
    "Cron",
    "DeleteSkill",
    "Exec",
    "Filesystem",
    "ListSkills",
    "Message",
    "ReadSkill",
    "Spawn",
    "Web",
    "WriteMemory",
)
PICOBOT_TOOLS_SCAN_CMD = (
    "strings $(which picobot) "
    "| grep -Eo '\\*tools\\.[A-Za-z0-9_]+Tool' "
    "| sed 's/^\\*tools\\.//' "
    "| sed 's/Tool$//' "
    "| sort -u"
)
try:
    _env_tools_cache_ttl = float(os.getenv("DIDIER_PICOBOT_TOOLS_CACHE_TTL_S", "30"))
except Exception:
    _env_tools_cache_ttl = 30.0
PICOBOT_TOOLS_CACHE_TTL_S = max(5.0, min(_env_tools_cache_ttl, 300.0))
MEMORY_WORKSPACE_DIR = PICOBOT_DATA_DIR / "workspace" / "memory"
MEMORY_HISTORY_DIR = MEMORY_WORKSPACE_DIR / "history"
MEMORY_TODAY_PATH = MEMORY_WORKSPACE_DIR / "TODAY.md"
MEMORY_LONG_TERM_PATH = MEMORY_WORKSPACE_DIR / "LONG_TERM.md"
MEMORY_HEARTBEAT_PATH = PICOBOT_DATA_DIR / "workspace" / "HEARTBEAT.md"
MEMORY_FILE_LIMIT_BYTES = 768 * 1024
MEMORY_FILE_TRIM_BYTES = 512 * 1024
MEMORY_TEXT_LIMIT = 320
PICOBOT_STUB_PREFIX = "(stub) echo:"
OPENAI_COMPAT_TIMEOUT_MAX_S = 5.5
try:
    _env_openai_timeout = float(os.getenv("DIDIER_PICOBOT_OPENAI_TIMEOUT_S", "3.2"))
except Exception:
    _env_openai_timeout = 3.2
OPENAI_COMPAT_TIMEOUT_S = max(0.5, min(_env_openai_timeout, OPENAI_COMPAT_TIMEOUT_MAX_S))
OPENAI_PLANNER_ENABLED = os.getenv("DIDIER_PICOBOT_OPENAI_PLANNER", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
try:
    _env_openai_planner_timeout = float(os.getenv("DIDIER_PICOBOT_OPENAI_PLANNER_TIMEOUT_S", "1.1"))
except Exception:
    _env_openai_planner_timeout = 1.1
OPENAI_PLANNER_TIMEOUT_S = max(0.3, min(_env_openai_planner_timeout, 2.5))
try:
    _env_openai_cache_ttl = float(os.getenv("DIDIER_PICOBOT_OPENAI_CACHE_TTL_S", "15"))
except Exception:
    _env_openai_cache_ttl = 15.0
OPENAI_CACHE_TTL_S = max(0.0, min(_env_openai_cache_ttl, 180.0))
try:
    _env_openai_circuit_open_s = float(os.getenv("DIDIER_PICOBOT_OPENAI_CIRCUIT_OPEN_S", "20"))
except Exception:
    _env_openai_circuit_open_s = 20.0
OPENAI_CIRCUIT_OPEN_S = max(2.0, min(_env_openai_circuit_open_s, 120.0))
try:
    _env_openai_circuit_threshold = int(os.getenv("DIDIER_PICOBOT_OPENAI_CIRCUIT_THRESHOLD", "1"))
except Exception:
    _env_openai_circuit_threshold = 1
OPENAI_CIRCUIT_THRESHOLD = max(1, min(_env_openai_circuit_threshold, 6))
PICOBOT_CLI_MODE = str(os.getenv("DIDIER_PICOBOT_CLI_MODE", "off")).strip().lower()
PICOBOT_RUNTIME_HOME = str(os.getenv("DIDIER_PICOBOT_RUNTIME_HOME", "/home/picobot")).strip() or "/home/picobot"
try:
    _env_tool_timeout_max = float(os.getenv("DIDIER_PICOBOT_TOOL_TIMEOUT_MAX_S", "4.0"))
except Exception:
    _env_tool_timeout_max = 4.0
PICOBOT_TOOL_TIMEOUT_MAX_S = max(1.0, min(_env_tool_timeout_max, 8.0))

_STATE_LOCK = threading.Lock()
_STATE: dict[str, Any] = {
    "started_at": time.time(),
    "last_react_ts": 0.0,
    "last_react_ms": 0.0,
    "last_error": "",
    "react_calls": 0,
    "react_failures": 0,
    "stub_responses": 0,
    "openai_fallback_calls": 0,
    "openai_fallback_failures": 0,
    "memory_last_write_ts": 0.0,
    "memory_write_failures": 0,
    "memory_last_error": "",
    "tool_calls": 0,
    "tool_failures": 0,
    "tool_last_error": "",
    "tool_last_names": [],
    "planner_calls": 0,
    "planner_success": 0,
    "planner_last": "",
    "cli_mode": PICOBOT_CLI_MODE,
    "cli_disabled_due_stub": False,
}
_TOOLS_LOCK = threading.Lock()
_TOOLS_CACHE: dict[str, Any] = {"ts": 0.0, "payload": {}}
_MEMORY_LOCK = threading.Lock()
_CONFIG_LOCK = threading.Lock()
_CONFIG_CACHE: dict[str, Any] = {"path": "", "mtime": 0.0, "payload": {}}
_OPENAI_CACHE_LOCK = threading.Lock()
_OPENAI_CACHE: dict[str, dict[str, Any]] = {}
_OPENAI_GUARD_LOCK = threading.Lock()
_OPENAI_GUARD: dict[str, Any] = {
    "failure_count": 0,
    "open_until": 0.0,
    "last_error": "",
}

app = FastAPI(title=APP_TITLE)


def _bounded_timeout(value: float | int, default: float, upper: float = DEFAULT_TIMEOUT_S) -> float:
    try:
        timeout = float(value)
    except Exception:
        timeout = float(default)
    return max(0.1, min(timeout, upper))


def _run_command(
    cmd: list[str], timeout_s: float, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
        env=env,
    )


def _load_picobot_config_payload() -> dict[str, Any]:
    config_path = PICOBOT_DATA_DIR / "config.json"
    if not config_path.exists() or not config_path.is_file():
        return {}
    try:
        mtime = float(config_path.stat().st_mtime)
    except Exception:
        mtime = 0.0
    with _CONFIG_LOCK:
        if (
            _CONFIG_CACHE.get("path") == str(config_path)
            and float(_CONFIG_CACHE.get("mtime") or 0.0) == mtime
            and isinstance(_CONFIG_CACHE.get("payload"), dict)
        ):
            return dict(_CONFIG_CACHE.get("payload") or {})
        try:
            payload = config_path.read_text(encoding="utf-8")
            parsed = json.loads(payload)
            data = parsed if isinstance(parsed, dict) else {}
        except Exception:
            data = {}
        _CONFIG_CACHE["path"] = str(config_path)
        _CONFIG_CACHE["mtime"] = mtime
        _CONFIG_CACHE["payload"] = data
        return dict(data)


def _load_picobot_llm_settings() -> dict[str, str]:
    data = _load_picobot_config_payload()
    llm = data.get("llm", {}) if isinstance(data, dict) else {}
    providers = data.get("providers", {}) if isinstance(data, dict) else {}
    openai_cfg = providers.get("openai", {}) if isinstance(providers, dict) else {}
    agent = data.get("agent", {}) if isinstance(data, dict) else {}
    base_url = str(
        (
            llm.get("base_url")
            if isinstance(llm, dict)
            else ""
        )
        or (
            llm.get("endpoint")
            if isinstance(llm, dict)
            else ""
        )
        or (
            openai_cfg.get("apiBase")
            if isinstance(openai_cfg, dict)
            else ""
        )
        or os.getenv("OPENAI_API_BASE", "")
    ).strip()
    api_key = str(
        (
            llm.get("api_key")
            if isinstance(llm, dict)
            else ""
        )
        or (
            openai_cfg.get("apiKey")
            if isinstance(openai_cfg, dict)
            else ""
        )
        or os.getenv("OPENAI_API_KEY", "")
    ).strip()
    model = str(
        (
            llm.get("model")
            if isinstance(llm, dict)
            else ""
        )
        or os.getenv("PICOBOT_MODEL", "")
    ).strip()
    system_prompt = str(
        (
            llm.get("system_prompt")
            if isinstance(llm, dict)
            else ""
        )
        or (
            agent.get("system_prompt")
            if isinstance(agent, dict)
            else ""
        )
    ).strip()
    return {
        "base_url": base_url.rstrip("/"),
        "api_key": api_key,
        "model": model,
        "system_prompt": system_prompt,
    }


def _load_picobot_config_tools() -> list[dict[str, Any]]:
    data = _load_picobot_config_payload()
    tools = data.get("tools", []) if isinstance(data, dict) else []
    if not isinstance(tools, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in tools:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        endpoint = str(item.get("endpoint") or item.get("url") or "").strip()
        try:
            timeout_seconds = float(item.get("timeout_seconds", 2.0) or 2.0)
        except Exception:
            timeout_seconds = 2.0
        normalized.append(
            {
                "name": name,
                "enabled": bool(item.get("enabled", True)),
                "type": str(item.get("type", "http")).strip() or "http",
                "method": str(item.get("method", "GET")).strip().upper() or "GET",
                "endpoint": endpoint or None,
                "timeout_seconds": timeout_seconds,
            }
        )
    return normalized


def _scan_builtin_tools() -> tuple[list[str], str | None]:
    cmd = ["docker", "exec", PICOBOT_CONTAINER, "sh", "-lc", PICOBOT_TOOLS_SCAN_CMD]
    try:
        proc = _run_command(cmd, _bounded_timeout(DEFAULT_TIMEOUT_S, DEFAULT_TIMEOUT_S))
    except Exception as exc:
        return [], str(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "tool scan failed").strip()
        return [], detail
    names: list[str] = []
    for raw in str(proc.stdout or "").splitlines():
        value = str(raw).strip()
        if not value:
            continue
        names.append(value)
    return sorted(set(names)), None


def _tools_snapshot(refresh: bool = False) -> dict[str, Any]:
    now = time.time()
    with _TOOLS_LOCK:
        cached = dict(_TOOLS_CACHE.get("payload") or {})
        cached_ts = float(_TOOLS_CACHE.get("ts") or 0.0)
    if not refresh and cached and (now - cached_ts) < PICOBOT_TOOLS_CACHE_TTL_S:
        return cached

    configured_tools = _load_picobot_config_tools()
    builtin_tools, scan_error = _scan_builtin_tools()
    source = "docker_exec"
    if not builtin_tools:
        builtin_tools = list(PICOBOT_EXPECTED_BUILTIN_TOOLS)
        source = "expected_fallback"

    expected = list(PICOBOT_EXPECTED_BUILTIN_TOOLS)
    missing = [name for name in expected if name not in builtin_tools]
    payload = {
        "source": source,
        "scan_error": scan_error,
        "builtin_tools": builtin_tools,
        "builtin_tools_count": len(builtin_tools),
        "expected_builtin_tools": expected,
        "expected_builtin_tools_count": len(expected),
        "missing_builtin_tools": missing,
        "install_required": bool(missing),
        "configured_tools": configured_tools,
        "configured_tools_count": len(configured_tools),
        "enabled_configured_tools_count": sum(1 for item in configured_tools if bool(item.get("enabled", False))),
        "ts": now,
    }
    with _TOOLS_LOCK:
        _TOOLS_CACHE["ts"] = now
        _TOOLS_CACHE["payload"] = payload
    return payload


def _container_running() -> tuple[bool, str]:
    timeout_s = _bounded_timeout(DEFAULT_TIMEOUT_S, DEFAULT_TIMEOUT_S)
    cmd = ["docker", "inspect", "-f", "{{.State.Running}}", PICOBOT_CONTAINER]
    try:
        proc = _run_command(cmd, timeout_s)
    except Exception as exc:
        return False, str(exc)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "container inspect failed").strip()
        return False, detail
    running = str(proc.stdout or "").strip().lower() == "true"
    return running, "running" if running else "stopped"


def _extract_reply(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    return lines[-1]


def _is_stub_reply(reply: str) -> bool:
    return str(reply or "").strip().lower().startswith(PICOBOT_STUB_PREFIX)


def _extract_openai_response_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    if isinstance(choices, list) and choices:
        first = choices[0] if isinstance(choices[0], dict) else {}
        message = first.get("message", {}) if isinstance(first, dict) else {}
        if isinstance(message, dict):
            content = str(message.get("content", "")).strip()
            if content:
                return content
        first_text = str(first.get("text", "")).strip() if isinstance(first, dict) else ""
        if first_text:
            return first_text
    response_text = str(payload.get("response", "")).strip() if isinstance(payload, dict) else ""
    if response_text:
        return response_text
    return str(payload.get("content", "")).strip() if isinstance(payload, dict) else ""


def _openai_cache_key(
    *,
    namespace: str,
    base_url: str,
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> str:
    payload = {
        "namespace": namespace,
        "base_url": base_url,
        "model": model,
        "messages": messages,
        "max_tokens": int(max_tokens),
        "temperature": float(temperature),
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def _openai_cache_get(cache_key: str) -> str | None:
    if OPENAI_CACHE_TTL_S <= 0.0:
        return None
    now = time.time()
    with _OPENAI_CACHE_LOCK:
        entry = _OPENAI_CACHE.get(cache_key, {})
        if not isinstance(entry, dict):
            return None
        ts = float(entry.get("ts", 0.0) or 0.0)
        value = str(entry.get("response", "")).strip()
        if not value:
            return None
        if (now - ts) > OPENAI_CACHE_TTL_S:
            _OPENAI_CACHE.pop(cache_key, None)
            return None
        return value


def _openai_cache_set(cache_key: str, response: str) -> None:
    if OPENAI_CACHE_TTL_S <= 0.0:
        return
    now = time.time()
    clean_response = str(response or "").strip()
    if not clean_response:
        return
    with _OPENAI_CACHE_LOCK:
        _OPENAI_CACHE[cache_key] = {"ts": now, "response": clean_response}
        # Keep cache bounded.
        if len(_OPENAI_CACHE) > 128:
            ordered = sorted(
                _OPENAI_CACHE.items(),
                key=lambda item: float((item[1] or {}).get("ts", 0.0) or 0.0),
            )
            for key, _ in ordered[:32]:
                _OPENAI_CACHE.pop(key, None)


def _openai_guard_open_error() -> str | None:
    now = time.time()
    with _OPENAI_GUARD_LOCK:
        open_until = float(_OPENAI_GUARD.get("open_until", 0.0) or 0.0)
        if open_until > now:
            remaining = max(0.0, open_until - now)
            return f"openai_compat circuit_open:{remaining:.1f}s"
    return None


def _openai_guard_record_failure(error: str) -> None:
    now = time.time()
    with _OPENAI_GUARD_LOCK:
        failure_count = int(_OPENAI_GUARD.get("failure_count", 0) or 0) + 1
        _OPENAI_GUARD["failure_count"] = failure_count
        _OPENAI_GUARD["last_error"] = str(error or "")
        if failure_count >= OPENAI_CIRCUIT_THRESHOLD:
            _OPENAI_GUARD["open_until"] = now + OPENAI_CIRCUIT_OPEN_S


def _openai_guard_record_success() -> None:
    with _OPENAI_GUARD_LOCK:
        _OPENAI_GUARD["failure_count"] = 0
        _OPENAI_GUARD["open_until"] = 0.0
        _OPENAI_GUARD["last_error"] = ""


def _openai_chat_request(
    *,
    llm_settings: dict[str, str],
    messages: list[dict[str, str]],
    timeout_s: float,
    max_tokens: int,
    temperature: float,
    cache_namespace: str = "",
    use_cache: bool = True,
    guard_reset_on_success: bool = True,
) -> dict[str, Any]:
    base_url = str(llm_settings.get("base_url", "")).strip().rstrip("/")
    model = str(llm_settings.get("model", "")).strip()
    api_key = str(llm_settings.get("api_key", "")).strip()
    if not base_url:
        return {"ok": False, "error": "openai_compat base_url missing"}
    if not model:
        return {"ok": False, "error": "openai_compat model missing"}

    try:
        request_timeout = float(timeout_s)
    except Exception:
        request_timeout = DEFAULT_TIMEOUT_S
    request_timeout = max(0.2, min(request_timeout, OPENAI_COMPAT_TIMEOUT_MAX_S))
    clean_messages = [item for item in messages if isinstance(item, dict) and item.get("content")]
    if not clean_messages:
        return {"ok": False, "error": "openai_compat missing messages"}

    guard_error = _openai_guard_open_error()
    if guard_error:
        return {"ok": False, "error": guard_error}

    cache_key = ""
    if use_cache and cache_namespace:
        cache_key = _openai_cache_key(
            namespace=cache_namespace,
            base_url=base_url,
            model=model,
            messages=clean_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        cached = _openai_cache_get(cache_key)
        if cached:
            return {
                "ok": True,
                "response": cached,
                "cached": True,
                "source": "openai_compat_cache",
            }

    body = {
        "model": model,
        "messages": clean_messages,
        "temperature": float(temperature),
        "max_tokens": int(max(24, min(int(max_tokens), 360))),
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=request_timeout) as response:
            raw = response.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = str(exc)
        error = f"openai_compat http {exc.code}: {_clip_memory_text(detail, 200)}"
        _openai_guard_record_failure(error)
        return {
            "ok": False,
            "error": error,
        }
    except Exception as exc:
        error = f"openai_compat request failed: {exc}"
        _openai_guard_record_failure(error)
        return {"ok": False, "error": error}

    try:
        payload = json.loads(raw)
    except Exception:
        payload = {}
    reply_text = _extract_openai_response_text(payload if isinstance(payload, dict) else {})
    if not reply_text:
        _openai_guard_record_failure("openai_compat empty response")
        return {"ok": False, "error": "openai_compat empty response"}
    if guard_reset_on_success:
        _openai_guard_record_success()
    if cache_key:
        _openai_cache_set(cache_key, reply_text)
    return {
        "ok": True,
        "response": reply_text,
        "cached": False,
        "source": "openai_compat",
    }


def _extract_json_object_from_text(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE).strip()
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        candidate = raw[start : end + 1]
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return None
    return None


def _plan_tools_with_openai(
    *,
    prompt: str,
    tools: list[dict[str, Any]],
    timeout_s: float,
) -> dict[str, Any] | None:
    if not OPENAI_PLANNER_ENABLED:
        return None
    enabled_tools = [item for item in tools if bool(item.get("enabled", True))]
    if not enabled_tools:
        return None
    llm = _load_picobot_llm_settings()
    if not str(llm.get("base_url", "")).strip() or not str(llm.get("model", "")).strip():
        return None

    tool_names = [str(item.get("name", "")).strip() for item in enabled_tools if str(item.get("name", "")).strip()]
    if not tool_names:
        return None
    known = {name.lower(): name for name in tool_names}
    planner_timeout_s = _bounded_timeout(
        min(float(timeout_s), OPENAI_PLANNER_TIMEOUT_S),
        default=OPENAI_PLANNER_TIMEOUT_S,
        upper=OPENAI_PLANNER_TIMEOUT_S,
    )

    planner_system = (
        "Tu es un routeur d'intention pour Didier. "
        "Retourne strictement un JSON valide, sans texte autour."
    )
    planner_user = (
        "Question utilisateur:\n"
        f"{str(prompt or '').strip()}\n\n"
        "Outils disponibles:\n"
        f"{', '.join(tool_names)}\n\n"
        "Schema JSON attendu:\n"
        "{"
        "\"intent\":\"chat|status|vision|web|action|unknown\","
        "\"answer_mode\":\"llm_only|tool_then_llm|tool_only\","
        "\"needs_tools\":[\"tool_name\"],"
        "\"reason\":\"courte raison\""
        "}\n"
        "Contraintes:\n"
        "- needs_tools doit contenir uniquement des noms de la liste\n"
        "- vide si aucun outil requis\n"
        "- JSON uniquement"
    )
    messages = [
        {"role": "system", "content": planner_system},
        {"role": "user", "content": planner_user},
    ]
    result = _openai_chat_request(
        llm_settings=llm,
        messages=messages,
        timeout_s=planner_timeout_s,
        max_tokens=120,
        temperature=0.0,
        cache_namespace="planner",
        use_cache=True,
        guard_reset_on_success=False,
    )
    if not result.get("ok", False):
        return None
    parsed = _extract_json_object_from_text(str(result.get("response", "")))
    if not isinstance(parsed, dict):
        return None
    raw_needs = parsed.get("needs_tools", [])
    selected: list[str] = []
    if isinstance(raw_needs, list):
        for item in raw_needs:
            name = str(item or "").strip().lower()
            if not name:
                continue
            normalized = known.get(name, "")
            if not normalized:
                continue
            if normalized not in selected:
                selected.append(normalized)
    answer_mode = str(parsed.get("answer_mode", "")).strip().lower() or "llm_only"
    intent = str(parsed.get("intent", "")).strip().lower() or "unknown"
    reason = str(parsed.get("reason", "")).strip()
    return {
        "tools": selected,
        "answer_mode": answer_mode,
        "intent": intent,
        "reason": _clip_memory_text(reason, 80),
    }


def _cli_mode_uses_cli() -> bool:
    mode = str(PICOBOT_CLI_MODE or "").strip().lower()
    if mode in {"off", "disable", "disabled", "openai", "bridge"}:
        return False
    if mode in {"on", "cli", "force", "prefer_cli"}:
        return True
    # "auto": disable CLI when repeated stub detected.
    with _STATE_LOCK:
        return not bool(_STATE.get("cli_disabled_due_stub", False))


_WEB_LOOKUP_TOOL_NAMES = {
    "web_lookup",
    "web_search",
    "internet_search",
    "search_web",
    "get_web_answer",
}

_WEB_LOOKUP_FORCE_HINTS = {
    "internet",
    "web",
    "en ligne",
    "online",
    "actualite",
    "actualites",
    "news",
    "meteo",
    "weather",
    "temperature",
    "forecast",
    "prix",
    "cours",
    "bourse",
    "crypto",
    "bitcoin",
    "ethereum",
    "taux",
    "change",
    "trafic",
    "horaire",
    "horaires",
    "resultat",
    "resultats",
    "score",
    "match",
    "aujourd hui",
    "demain",
    "ce soir",
    "ce weekend",
    "ce week end",
    "maintenant",
    "en ce moment",
}

_WEB_LOOKUP_LOCAL_HINTS = {
    "didier",
    "pixel",
    "camera",
    "vision",
    "npu",
    "asr",
    "audio",
    "worker",
    "workers",
    "service",
    "raspberry",
    "pi",
}

_WEB_LOOKUP_QUESTION_PREFIXES = {
    "qui",
    "quoi",
    "quand",
    "ou",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "combien",
    "who",
    "what",
    "when",
    "where",
    "how",
}

_WEB_LOOKUP_SMALLTALK_PREFIXES = (
    "salut",
    "bonjour",
    "bonsoir",
    "merci",
    "ca va",
    "comment vas tu",
    "qui es tu",
    "tu es qui",
)

_WEB_QUERY_STOPWORDS = {
    "a",
    "au",
    "aux",
    "avec",
    "ce",
    "ces",
    "combien",
    "comment",
    "dans",
    "de",
    "des",
    "dis",
    "donne",
    "du",
    "en",
    "est",
    "et",
    "fera",
    "fais",
    "is",
    "la",
    "le",
    "les",
    "moi",
    "on",
    "ou",
    "par",
    "peux",
    "peut",
    "pour",
    "quoi",
    "quand",
    "que",
    "quel",
    "quelle",
    "quelles",
    "quels",
    "qui",
    "recherche",
    "sur",
    "temps",
    "to",
    "tu",
    "un",
    "une",
    "va",
    "vas",
    "veux",
    "what",
    "who",
    "will",
    "you",
}

_WEB_FACT_PREFIXES = (
    "qui est",
    "who is",
    "what is",
    "c est quoi",
    "qu est ce que",
    "definition de",
    "definis",
    "definis moi",
    "définis",
    "définis moi",
)

_CRYPTO_KEYWORDS = {
    "bitcoin": "bitcoin",
    "btc": "bitcoin",
    "ethereum": "ethereum",
    "eth": "ethereum",
    "solana": "solana",
    "sol": "solana",
    "dogecoin": "dogecoin",
    "doge": "dogecoin",
    "cardano": "cardano",
    "ada": "cardano",
}

_EQUITY_QUERY_HINTS = {
    "action",
    "actions",
    "bourse",
    "cours",
    "stock",
    "share",
    "shares",
    "ticker",
    "capitalisation",
    "capitalization",
    "price",
    "prix",
    "cotation",
    "cotation",
}

_EQUITY_ENTITY_STOPWORDS = {
    "aujourd",
    "hui",
    "demain",
    "prix",
    "cours",
    "bourse",
    "action",
    "actions",
    "stock",
    "ticker",
    "share",
    "shares",
    "entreprise",
    "societe",
    "societe",
    "company",
    "cours",
    "valeur",
    "combien",
    "quel",
    "quelle",
    "quels",
    "quelles",
    "est",
    "du",
    "de",
    "des",
    "la",
    "le",
    "les",
    "d",
}

_EQUITY_ALIAS_TO_SYMBOL = {
    "airbus": "AIR.PA",
    "lvmh": "MC.PA",
    "totalenergies": "TTE.PA",
    "total": "TTE.PA",
    "sanofi": "SAN.PA",
    "renault": "RNO.PA",
    "apple": "AAPL",
    "microsoft": "MSFT",
    "tesla": "TSLA",
    "nvidia": "NVDA",
    "amazon": "AMZN",
    "alphabet": "GOOGL",
    "google": "GOOGL",
    "meta": "META",
}

_WEB_RSS_BLOCKED_DOMAINS = {
    "zhihu.com",
    "zhidao.baidu.com",
    "baidu.com",
}
_WEB_RSS_MIN_SCORE = 2.0
_WEB_QUERY_LOW_SIGNAL_TOKENS = {
    "action",
    "aujourd",
    "cours",
    "demain",
    "donne",
    "est",
    "hui",
    "infos",
    "info",
    "meteo",
    "news",
    "prix",
    "question",
    "reponse",
    "stock",
    "today",
    "web",
}

_NON_LATIN_RESPONSE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3040-\u30ff\u0400-\u04ff]")


def _normalize_prompt_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
    return text


def _contains_cjk_chars(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]", str(text)))


def _contains_non_latin_response(text: str) -> bool:
    if not text:
        return False
    return bool(_NON_LATIN_RESPONSE_RE.search(str(text)))


def _contains_prompt_phrase(norm_text: str, phrase: str) -> bool:
    tokens = [tok for tok in str(norm_text or "").split() if tok]
    phrase_tokens = [tok for tok in _normalize_prompt_text(phrase).split() if tok]
    if not tokens or not phrase_tokens:
        return False
    size = len(phrase_tokens)
    if size == 1:
        return phrase_tokens[0] in tokens
    for index in range(0, len(tokens) - size + 1):
        if tokens[index : index + size] == phrase_tokens:
            return True
    return False


def _prompt_needs_web_lookup(prompt: str) -> bool:
    norm = _normalize_prompt_text(prompt)
    if not norm:
        return False
    if any(norm.startswith(prefix) for prefix in _WEB_LOOKUP_SMALLTALK_PREFIXES):
        return False
    if any(_contains_prompt_phrase(norm, hint) for hint in _WEB_LOOKUP_FORCE_HINTS):
        return True
    first_word = norm.split(" ", 1)[0]
    if first_word not in _WEB_LOOKUP_QUESTION_PREFIXES:
        return False
    if any(_contains_prompt_phrase(norm, hint) for hint in _WEB_LOOKUP_LOCAL_HINTS):
        return False
    return True


def _sanitize_web_lookup_query(prompt: str) -> str:
    if _looks_like_weather_prompt(prompt):
        location = _extract_weather_location(prompt)
        normalized = _normalize_prompt_text(prompt)
        weather_query_parts = ["meteo"]
        if location:
            weather_query_parts.append(location)
        if "demain" in normalized or "tomorrow" in normalized:
            weather_query_parts.append("demain")
        return " ".join(part for part in weather_query_parts if part).strip()
    raw = str(prompt or "").strip().lower()
    if not raw:
        return ""
    cleaned = raw.replace("-", " ").replace("_", " ")
    cleaned = re.sub(r"[^\w\sàâäéèêëîïôöùûüçœæ]", " ", cleaned, flags=re.IGNORECASE)
    tokens = [tok for tok in cleaned.split() if tok and tok not in _WEB_QUERY_STOPWORDS]
    if len(tokens) < 2:
        norm = _normalize_prompt_text(prompt)
        tokens = [tok for tok in norm.split() if tok]
    if not tokens:
        return ""
    return " ".join(tokens[:12]).strip()


def _extract_fact_query(prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return ""
    cleaned = _normalize_prompt_text(text)
    for prefix in _WEB_FACT_PREFIXES:
        if cleaned.startswith(prefix):
            pattern = re.compile(rf"^\s*{re.escape(prefix)}\s*", flags=re.IGNORECASE)
            stripped = pattern.sub("", cleaned, count=1).strip()
            tokens = [
                tok
                for tok in stripped.split()
                if tok
                and tok
                not in {
                    "a",
                    "au",
                    "aux",
                    "actuel",
                    "actuellement",
                    "ce",
                    "de",
                    "des",
                    "du",
                    "en",
                    "est",
                    "la",
                    "le",
                    "les",
                    "un",
                    "une",
                }
            ]
            if tokens:
                return " ".join(tokens[:10]).strip()
            return stripped
    return cleaned


def _looks_like_fact_lookup_prompt(prompt: str) -> bool:
    norm = _normalize_prompt_text(prompt)
    if not norm:
        return False
    if any(_contains_prompt_phrase(norm, hint) for hint in _WEB_LOOKUP_LOCAL_HINTS):
        return False
    return any(norm.startswith(prefix) for prefix in _WEB_FACT_PREFIXES)


def _call_wikipedia_lookup(prompt: str, timeout_s: float) -> tuple[bool, dict[str, Any]]:
    query = _extract_fact_query(prompt)
    if not query:
        return False, {"error": "empty_fact_query"}
    query_quoted = urllib.parse.quote(query)
    opensearch_url = (
        "https://fr.wikipedia.org/w/api.php"
        f"?action=opensearch&search={query_quoted}&limit=1&namespace=0&format=json"
    )
    req = urllib.request.Request(
        opensearch_url,
        headers={"Accept": "application/json", "User-Agent": "Didier-Picobot-Bridge/4.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=min(timeout_s, 3.0)) as response:
            raw = response.read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
    except Exception as exc:
        return False, {"error": f"wikipedia_opensearch_failed:{exc}"}

    title = ""
    page_url = ""
    if isinstance(payload, list) and len(payload) >= 4:
        titles = payload[1] if isinstance(payload[1], list) else []
        urls = payload[3] if isinstance(payload[3], list) else []
        if titles:
            title = str(titles[0] or "").strip()
        if urls:
            page_url = str(urls[0] or "").strip()
    if not title:
        return False, {"error": "wikipedia_no_result"}

    summary_url = "https://fr.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title)
    summary_req = urllib.request.Request(
        summary_url,
        headers={"Accept": "application/json", "User-Agent": "Didier-Picobot-Bridge/4.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(summary_req, timeout=min(timeout_s, 3.0)) as response:
            summary_raw = response.read().decode("utf-8", errors="ignore")
        summary_payload = json.loads(summary_raw)
    except Exception:
        summary_payload = {}

    extract = str(summary_payload.get("extract", "")).strip() if isinstance(summary_payload, dict) else ""
    content_urls = summary_payload.get("content_urls", {}) if isinstance(summary_payload, dict) else {}
    desktop = content_urls.get("desktop", {}) if isinstance(content_urls, dict) else {}
    summary_link = str(desktop.get("page", "")).strip() if isinstance(desktop, dict) else ""
    if summary_link:
        page_url = summary_link
    if not extract:
        return False, {"error": "wikipedia_summary_missing", "title": title, "url": page_url}
    return True, {
        "title": title,
        "summary": extract,
        "url": page_url,
        "source": "wikipedia",
    }


def _detect_crypto_asset(prompt: str) -> str:
    norm = _normalize_prompt_text(prompt)
    for token in norm.split():
        asset = _CRYPTO_KEYWORDS.get(token)
        if asset:
            return asset
    return ""


def _call_crypto_price_lookup(prompt: str, timeout_s: float) -> tuple[bool, dict[str, Any]]:
    asset = _detect_crypto_asset(prompt)
    if not asset:
        return False, {"error": "crypto_asset_not_found"}
    endpoint = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={urllib.parse.quote(asset)}"
        "&vs_currencies=eur,usd"
        "&include_last_updated_at=true"
    )
    req = urllib.request.Request(
        endpoint,
        headers={"Accept": "application/json", "User-Agent": "Didier-Picobot-Bridge/4.0"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=min(timeout_s, 3.0)) as response:
            raw = response.read().decode("utf-8", errors="ignore")
        payload = json.loads(raw)
    except Exception as exc:
        return False, {"error": f"coingecko_failed:{exc}"}
    data = payload.get(asset, {}) if isinstance(payload, dict) else {}
    if not isinstance(data, dict):
        return False, {"error": "coingecko_invalid_payload"}
    price_eur = data.get("eur")
    price_usd = data.get("usd")
    if price_eur is None and price_usd is None:
        return False, {"error": "coingecko_missing_price"}
    updated_at = data.get("last_updated_at")
    return True, {
        "source": "coingecko",
        "asset": asset,
        "price_eur": price_eur,
        "price_usd": price_usd,
        "last_updated_at": updated_at,
    }


def _looks_like_equity_price_prompt(prompt: str) -> bool:
    norm = _normalize_prompt_text(prompt)
    if not norm:
        return False
    tokens = set(norm.split())
    if tokens & _WEB_LOOKUP_LOCAL_HINTS:
        return False
    if tokens & _EQUITY_QUERY_HINTS:
        return True
    return bool(re.search(r"\b[A-Z]{1,5}(?:\.[A-Z]{1,3})\b", str(prompt or "")))


def _extract_equity_query_terms(prompt: str, limit: int = 5) -> list[str]:
    norm = _normalize_prompt_text(prompt)
    if not norm:
        return []
    terms: list[str] = []
    for token in norm.split():
        if not token:
            continue
        if token in _WEB_QUERY_STOPWORDS or token in _EQUITY_ENTITY_STOPWORDS:
            continue
        if len(token) < 2:
            continue
        terms.append(token)
        if len(terms) >= max(1, limit):
            break
    return terms


def _resolve_equity_alias_symbol(prompt: str) -> str:
    norm = _normalize_prompt_text(prompt)
    if not norm:
        return ""
    tokens = norm.split()
    for key, symbol in _EQUITY_ALIAS_TO_SYMBOL.items():
        key_tokens = key.split()
        if not key_tokens:
            continue
        if len(key_tokens) == 1 and key_tokens[0] in tokens:
            return symbol
        if " ".join(key_tokens) in norm:
            return symbol
    match = re.search(r"\b([A-Z]{1,5}(?:\.[A-Z]{1,3})?)\b", str(prompt or ""))
    if match:
        return str(match.group(1)).strip().upper()
    return ""


def _score_equity_candidate(
    candidate: dict[str, Any],
    *,
    query_terms: list[str],
) -> float:
    symbol = str(candidate.get("symbol", "")).strip().upper()
    quote_type = str(candidate.get("quoteType", "")).strip().upper()
    shortname = str(candidate.get("shortname", "")).strip()
    longname = str(candidate.get("longname", "")).strip()
    exchange = str(candidate.get("exchange", "")).strip().upper()
    combined = _normalize_prompt_text(f"{symbol} {shortname} {longname}")
    score = 0.0
    if quote_type == "EQUITY":
        score += 3.0
    elif quote_type:
        score += 1.0
    if exchange in {"PAR", "XPAR", "EPA", "EURONEXT"}:
        score += 0.5
    if symbol.endswith(".PA"):
        score += 0.5
    overlap = sum(1 for term in query_terms if term and term in combined)
    score += float(overlap) * 2.0
    if query_terms and overlap == 0:
        score -= 3.0
    if not symbol:
        score -= 6.0
    return score


def _format_epoch_utc(epoch_value: Any) -> str:
    try:
        epoch = int(epoch_value)
    except Exception:
        return ""
    if epoch <= 0:
        return ""
    try:
        return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
    except Exception:
        return ""


def _pick_equity_candidate(search_payload: dict[str, Any], prompt: str) -> dict[str, Any] | None:
    quotes = search_payload.get("quotes", []) if isinstance(search_payload, dict) else []
    if not isinstance(quotes, list) or not quotes:
        return None
    query_terms = _extract_equity_query_terms(prompt, limit=6)
    best: dict[str, Any] | None = None
    best_score = -999.0
    for entry in quotes[:12]:
        if not isinstance(entry, dict):
            continue
        score = _score_equity_candidate(entry, query_terms=query_terms)
        if score > best_score:
            best_score = score
            best = entry
    if best is None:
        return None
    if query_terms and best_score < 1.0:
        return None
    return best


def _call_equity_price_lookup(prompt: str, timeout_s: float) -> tuple[bool, dict[str, Any]]:
    if not _looks_like_equity_price_prompt(prompt):
        return False, {"error": "not_equity_prompt"}
    symbol = _resolve_equity_alias_symbol(prompt)
    query_terms = _extract_equity_query_terms(prompt, limit=6)
    if not symbol:
        if not query_terms:
            return False, {"error": "equity_query_missing_entity"}
        search_query = " ".join(query_terms[:4]).strip()
        search_url = (
            "https://query1.finance.yahoo.com/v1/finance/search"
            f"?q={urllib.parse.quote_plus(search_query)}&quotesCount=8&newsCount=0"
        )
        try:
            search_payload = _open_json_url(search_url, min(timeout_s, 3.0))
        except Exception as exc:
            return False, {"error": f"yahoo_search_failed:{exc}"}
        candidate = _pick_equity_candidate(search_payload, prompt)
        if not candidate:
            return False, {"error": "equity_symbol_not_found"}
        symbol = str(candidate.get("symbol", "")).strip().upper()
        if not symbol:
            return False, {"error": "equity_symbol_empty"}

    quote_url = (
        "https://query1.finance.yahoo.com/v7/finance/quote"
        f"?symbols={urllib.parse.quote_plus(symbol)}"
    )
    try:
        quote_payload = _open_json_url(quote_url, min(timeout_s, 3.0))
    except Exception as exc:
        return False, {"error": f"yahoo_quote_failed:{exc}", "symbol": symbol}
    quote_response = quote_payload.get("quoteResponse", {}) if isinstance(quote_payload, dict) else {}
    rows = quote_response.get("result", []) if isinstance(quote_response, dict) else []
    if not isinstance(rows, list) or not rows:
        return False, {"error": "yahoo_quote_empty", "symbol": symbol}
    row = rows[0] if isinstance(rows[0], dict) else {}
    market_price = row.get("regularMarketPrice")
    currency = str(row.get("currency", "")).strip()
    if market_price in (None, ""):
        return False, {"error": "yahoo_quote_missing_price", "symbol": symbol}
    change_pct = row.get("regularMarketChangePercent")
    market_time_iso = _format_epoch_utc(row.get("regularMarketTime"))
    name = str(
        row.get("shortName")
        or row.get("longName")
        or row.get("displayName")
        or symbol
    ).strip() or symbol
    return True, {
        "source": "yahoo_finance",
        "symbol": symbol,
        "name": name,
        "price": market_price,
        "currency": currency,
        "change_percent": change_pct,
        "market_time_utc": market_time_iso,
    }


def _looks_like_weather_prompt(prompt: str) -> bool:
    norm = _normalize_prompt_text(prompt)
    if not norm:
        return False
    tokens = set(norm.split())
    hints = {
        "meteo",
        "weather",
        "forecast",
        "temperature",
        "pluie",
        "neige",
        "vent",
        "temps",
    }
    return bool(tokens & hints)


def _extract_weather_location(prompt: str) -> str:
    text = str(prompt or "").strip()
    if not text:
        return ""
    matches = re.findall(r"\b(?:a|à|pour|sur)\b\s+(.+?)(?:\?|$)", text, flags=re.IGNORECASE)
    location = matches[-1].strip() if matches else text
    location = re.sub(r"^faire\s+", "", location, flags=re.IGNORECASE).strip()
    location = re.sub(
        r"\b(demain|tomorrow|aujourd'hui|aujourdhui|ce\s+soir|cette\s+semaine|week[- ]?end|maintenant|matin|apres[- ]?midi|soir)\b.*$",
        "",
        location,
        flags=re.IGNORECASE,
    ).strip(" ,.;:!?")
    location = re.sub(
        r"^(?:la\s+meteo\s+de\s+|meteo\s+de\s+|weather\s+(?:in|for)\s+)",
        "",
        location,
        flags=re.IGNORECASE,
    ).strip(" ,.;:!?")
    return location


def _wmo_weather_label(code: Any) -> str:
    try:
        value = int(code)
    except Exception:
        return "conditions variables"
    mapping = {
        0: "ciel degage",
        1: "globalement ensoleille",
        2: "partiellement nuageux",
        3: "nuageux",
        45: "brume",
        48: "brume givrante",
        51: "bruine faible",
        53: "bruine moderee",
        55: "bruine dense",
        56: "bruine verglaçante faible",
        57: "bruine verglaçante dense",
        61: "pluie faible",
        63: "pluie moderee",
        65: "pluie forte",
        66: "pluie verglaçante faible",
        67: "pluie verglaçante forte",
        71: "neige faible",
        73: "neige moderee",
        75: "neige forte",
        77: "grains de neige",
        80: "averses faibles",
        81: "averses moderees",
        82: "averses violentes",
        85: "averses de neige faibles",
        86: "averses de neige fortes",
        95: "orage",
        96: "orage avec grele faible",
        99: "orage avec grele forte",
    }
    return mapping.get(value, "conditions variables")


def _open_json_url(url: str, timeout_s: float) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Didier-Picobot-Bridge/4.0",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        raw = response.read().decode("utf-8", errors="ignore")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("invalid_json_payload")
    return data


def _nominatim_geocode(query: str, timeout_s: float) -> dict[str, Any] | None:
    q = str(query or "").strip()
    if not q:
        return None
    url = (
        "https://nominatim.openstreetmap.org/search"
        f"?format=jsonv2&limit=1&q={urllib.parse.quote_plus(q)}"
    )
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "Didier-Picobot-Bridge/4.0 (+didier.local)",
        },
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        raw = response.read().decode("utf-8", errors="ignore")
    payload = json.loads(raw)
    if not isinstance(payload, list) or not payload:
        return None
    item = payload[0] if isinstance(payload[0], dict) else {}
    lat = item.get("lat")
    lon = item.get("lon")
    if lat is None or lon is None:
        return None
    display = str(item.get("display_name", "")).strip()
    label = display.split(",")[0].strip() if display else q
    return {
        "latitude": float(lat),
        "longitude": float(lon),
        "name": label or q,
        "admin1": "",
        "country": "France",
    }


def _call_weather_lookup(prompt: str, timeout_s: float) -> tuple[bool, dict[str, Any]]:
    if not _looks_like_weather_prompt(prompt):
        return False, {"error": "not_weather_prompt"}
    location = _extract_weather_location(prompt)
    if not location:
        return False, {"error": "weather_location_missing"}
    normalized = _normalize_prompt_text(prompt)
    day_index = 1 if ("demain" in normalized or "tomorrow" in normalized) else 0
    try:
        geo_timeout = max(0.8, min(float(timeout_s) * 0.45, 2.5))
        forecast_timeout = max(0.8, min(float(timeout_s) - geo_timeout, 2.5))
        location_candidates: list[str] = []
        location_candidates.append(location)
        simplified = re.sub(r"\bdans\s+(?:le|la|les|l')\s+", " ", location, flags=re.IGNORECASE)
        simplified = re.sub(r"[,_/]+", " ", simplified)
        simplified = re.sub(r"\s+", " ", simplified).strip(" ,.;:!?")
        if simplified and simplified not in location_candidates:
            location_candidates.append(simplified)
        chunks = [
            chunk.strip(" ,.;:!?")
            for chunk in re.split(r",|\bdans\b", location, flags=re.IGNORECASE)
            if chunk and chunk.strip(" ,.;:!?")
        ]
        for chunk in chunks:
            if chunk not in location_candidates:
                location_candidates.append(chunk)
        if len(chunks) >= 2:
            merged = f"{chunks[0]} {chunks[-1]}".strip()
            if merged and merged not in location_candidates:
                location_candidates.append(merged)

        place: dict[str, Any] | None = None
        for candidate in location_candidates:
            geocode_url = (
                "https://geocoding-api.open-meteo.com/v1/search"
                f"?name={urllib.parse.quote_plus(candidate)}&count=1&language=fr&format=json"
            )
            geocode_payload = _open_json_url(geocode_url, geo_timeout)
            results = geocode_payload.get("results", [])
            if isinstance(results, list) and results:
                maybe_place = results[0] if isinstance(results[0], dict) else {}
                if maybe_place:
                    place = maybe_place
                    break
        if place is None:
            for candidate in location_candidates:
                try:
                    nomi = _nominatim_geocode(f"{candidate}, France", geo_timeout)
                    if nomi:
                        place = nomi
                        break
                except Exception:
                    continue
        if place is None:
            return False, {"error": "weather_geocode_not_found"}
        latitude = place.get("latitude")
        longitude = place.get("longitude")
        if latitude is None or longitude is None:
            return False, {"error": "weather_geocode_invalid"}
        forecast_url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={latitude}&longitude={longitude}"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode"
            "&timezone=Europe%2FParis"
        )
        forecast_payload = _open_json_url(forecast_url, forecast_timeout)
        daily = forecast_payload.get("daily", {})
        if not isinstance(daily, dict):
            return False, {"error": "weather_missing_daily"}
        dates = daily.get("time", [])
        tmax = daily.get("temperature_2m_max", [])
        tmin = daily.get("temperature_2m_min", [])
        rain = daily.get("precipitation_probability_max", [])
        wmo = daily.get("weathercode", [])
        if not isinstance(dates, list) or not dates:
            return False, {"error": "weather_missing_dates"}
        idx = day_index if day_index < len(dates) else 0
        target_date = str(dates[idx]) if idx < len(dates) else ""
        temp_min = tmin[idx] if isinstance(tmin, list) and idx < len(tmin) else None
        temp_max = tmax[idx] if isinstance(tmax, list) and idx < len(tmax) else None
        rain_max = rain[idx] if isinstance(rain, list) and idx < len(rain) else None
        wmo_code = wmo[idx] if isinstance(wmo, list) and idx < len(wmo) else None
        area_name = str(place.get("name", "")).strip() or location
        admin = str(place.get("admin1", "")).strip()
        country = str(place.get("country", "")).strip()
        if admin:
            area_name = f"{area_name}, {admin}"
        elif country:
            area_name = f"{area_name}, {country}"
        return True, {
            "source": "open_meteo",
            "location": area_name,
            "target_day": "demain" if day_index == 1 else "aujourd'hui",
            "date": target_date,
            "temp_min_c": temp_min,
            "temp_max_c": temp_max,
            "chance_of_rain_pct": rain_max,
            "summary": _wmo_weather_label(wmo_code),
            "weather_code": wmo_code,
        }
    except Exception as exc:
        return False, {"error": f"weather_lookup_failed:{exc}"}


def _tool_matches_prompt(tool_name: str, prompt: str) -> bool:
    normalized = str(prompt or "").strip().lower()
    name = str(tool_name or "").strip().lower()
    if not normalized or not name:
        return False
    if name in _WEB_LOOKUP_TOOL_NAMES:
        return _prompt_needs_web_lookup(prompt)
    if name == "get_system_status":
        keys = ("status", "sante", "health", "cpu", "memoire", "ram", "version", "charge")
        return any(token in normalized for token in keys)
    if name == "check_camera":
        keys = ("camera", "caméra", "vision", "npu", "flux", "detection", "détection")
        return any(token in normalized for token in keys)
    if name == "get_pixel_status":
        keys = ("pixel", "tpu", "smartphone", "telephone", "téléphone", "mobile")
        return any(token in normalized for token in keys)
    return name.replace("_", " ") in normalized or name in normalized


def _call_http_tool(
    tool: dict[str, Any],
    timeout_s: float,
    *,
    prompt: str = "",
) -> tuple[bool, dict[str, Any]]:
    endpoint = str(tool.get("endpoint") or "").strip()
    if not endpoint:
        return False, {"error": "missing_endpoint"}
    tool_name = str(tool.get("name", "")).strip().lower()
    query_text_raw = str(prompt or "").strip()
    query_text = query_text_raw
    if tool_name in _WEB_LOOKUP_TOOL_NAMES:
        weather_ok, weather_payload = _call_weather_lookup(query_text_raw, timeout_s)
        if weather_ok:
            return True, {"status": 200, "payload": weather_payload}
        crypto_ok, crypto_payload = _call_crypto_price_lookup(query_text_raw, timeout_s)
        if crypto_ok:
            return True, {"status": 200, "payload": crypto_payload}
        equity_ok, equity_payload = _call_equity_price_lookup(query_text_raw, timeout_s)
        if equity_ok:
            return True, {"status": 200, "payload": equity_payload}
        raw_lower = query_text_raw.lower()
        should_try_wiki = _looks_like_fact_lookup_prompt(query_text_raw) or raw_lower.startswith(
            (
                "qui est",
                "who is",
                "what is",
                "quel est",
                "quelle est",
                "c'est quoi",
                "c est quoi",
                "qu'est ce que",
                "qu est ce que",
            )
        )
        if should_try_wiki and not any(
            token in raw_lower
            for token in (
                "actualite",
                "actualité",
                "news",
                "meteo",
                "météo",
                "weather",
                "prix",
                "cours",
                "taux",
            )
        ):
            wiki_ok, wiki_payload = _call_wikipedia_lookup(query_text_raw, timeout_s)
            if wiki_ok:
                return True, {"status": 200, "payload": wiki_payload}
        query_text = _sanitize_web_lookup_query(query_text_raw) or query_text_raw
    if "{query}" in endpoint:
        endpoint = endpoint.replace("{query}", urllib.parse.quote_plus(query_text))
    if "{query_raw}" in endpoint:
        endpoint = endpoint.replace("{query_raw}", urllib.parse.quote(query_text, safe=""))
    method = str(tool.get("method", "GET")).strip().upper() or "GET"
    headers = {
        "Accept": "application/json, application/xml, text/xml, text/plain;q=0.9, */*;q=0.8",
        "User-Agent": "Didier-Picobot-Bridge/4.0",
    }
    data: bytes | None = None
    if method not in {"GET", "POST"}:
        method = "GET"
    req = urllib.request.Request(endpoint, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as response:
            raw = response.read().decode("utf-8", errors="ignore")
            status = int(getattr(response, "status", 200))
    except urllib.error.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = str(exc)
        return False, {"error": f"http_{exc.code}", "detail": _clip_memory_text(detail, 180)}
    except Exception as exc:
        return False, {"error": f"request_failed:{exc}"}
    try:
        payload = json.loads(raw)
    except Exception:
        if tool_name in _WEB_LOOKUP_TOOL_NAMES:
            payload = {
                "raw": str(raw or "")[:12000],
                "query": query_text_raw,
                "query_sanitized": query_text,
            }
        else:
            payload = {"raw": _clip_memory_text(raw, 180)}
    if tool_name in _WEB_LOOKUP_TOOL_NAMES and isinstance(payload, dict):
        payload.setdefault("query", query_text_raw)
        payload.setdefault("query_sanitized", query_text)
    return True, {"status": status, "payload": payload}


def _query_tokens_for_relevance(query: str, limit: int = 8) -> list[str]:
    norm = _normalize_prompt_text(query)
    if not norm:
        return []
    tokens = [
        tok
        for tok in norm.split()
        if tok
        and tok not in _WEB_QUERY_STOPWORDS
        and tok not in _WEB_QUERY_LOW_SIGNAL_TOKENS
        and len(tok) >= 4
    ]
    if not tokens:
        tokens = [
            tok
            for tok in norm.split()
            if tok
            and tok not in _WEB_QUERY_STOPWORDS
            and tok not in _WEB_QUERY_LOW_SIGNAL_TOKENS
            and len(tok) >= 3
        ]
    ranked = sorted(tokens, key=len, reverse=True)
    unique: list[str] = []
    for token in ranked:
        if token not in unique:
            unique.append(token)
        if len(unique) >= max(1, limit):
            break
    return unique


def _domain_from_link(link: str) -> str:
    try:
        netloc = urllib.parse.urlparse(str(link or "")).netloc.lower().strip()
    except Exception:
        netloc = ""
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc


def _domain_blocked(domain: str) -> bool:
    if not domain:
        return False
    for blocked in _WEB_RSS_BLOCKED_DOMAINS:
        if domain == blocked or domain.endswith("." + blocked):
            return True
    return False


def _rss_item_score(
    *,
    title: str,
    description: str,
    link: str,
    query_tokens: list[str],
) -> float:
    score = 0.0
    combined = f"{title} {description}".strip()
    norm_combined = _normalize_prompt_text(combined)
    domain = _domain_from_link(link)
    if not combined:
        return -10.0
    if _contains_cjk_chars(combined):
        score -= 8.0
    if _domain_blocked(domain):
        score -= 6.0
    if "wikipedia.org" in domain:
        score += 2.0
    if description and len(description) >= 40:
        score += 0.5
    if query_tokens:
        overlap = sum(1 for token in query_tokens if token in norm_combined)
        score += float(overlap) * 2.0
        if overlap == 0:
            score -= 2.0
    return score


def _extract_bing_rss_head(payload: dict[str, Any]) -> dict[str, str]:
    candidates = _extract_bing_rss_candidates(payload, limit=1)
    return candidates[0] if candidates else {}


def _extract_bing_rss_candidates(payload: dict[str, Any], limit: int = 3) -> list[dict[str, str]]:
    if not isinstance(payload, dict):
        return []
    raw = str(payload.get("raw", "")).strip()
    if not raw.startswith("<?xml"):
        return []
    try:
        root = ET.fromstring(raw)
    except Exception:
        return []
    channel = root.find("channel")
    if channel is None:
        return []
    items = channel.findall("item")
    if not items:
        return []

    query_raw = str(payload.get("query") or payload.get("query_sanitized") or "").strip()
    query_tokens = _query_tokens_for_relevance(query_raw)

    scored: list[tuple[float, dict[str, str]]] = []
    for item in items:
        title = str(item.findtext("title", default="") or "").strip()
        link = str(item.findtext("link", default="") or "").strip()
        description = str(item.findtext("description", default="") or "").strip()
        pub_date = str(item.findtext("pubDate", default="") or "").strip()
        if not (title or description):
            continue
        score = _rss_item_score(
            title=title,
            description=description,
            link=link,
            query_tokens=query_tokens,
        )
        candidate = {
            "title": title,
            "link": link,
            "description": description,
            "pub_date": pub_date,
        }
        scored.append((score, candidate))

    if not scored:
        return []

    scored.sort(key=lambda item: item[0], reverse=True)
    selected: list[dict[str, str]] = []
    for score, entry in scored:
        if query_tokens and score < _WEB_RSS_MIN_SCORE:
            continue
        message = f"{entry.get('title', '')} {entry.get('description', '')}".strip()
        if query_tokens and _contains_cjk_chars(message):
            continue
        selected.append(entry)
        if len(selected) >= max(1, int(limit)):
            break
    return selected


def _summarize_tool_result(tool_name: str, result: dict[str, Any]) -> str:
    name = str(tool_name or "").strip().lower()
    payload = result.get("payload", {}) if isinstance(result, dict) else {}
    if not isinstance(payload, dict):
        return _clip_memory_text(json.dumps(result, ensure_ascii=False), 180)
    if name == "get_system_status":
        summary = {
            "status": payload.get("status"),
            "name": payload.get("name"),
            "state": payload.get("state"),
            "version": payload.get("version"),
        }
        return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 140)
    if name == "check_camera":
        summary = {
            "ready": payload.get("ready"),
            "detector": payload.get("detector"),
            "last_count": payload.get("last_count"),
            "last_error": payload.get("last_error"),
        }
        return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 160)
    if name == "get_pixel_status":
        hw = payload.get("hardware_profile", {}) if isinstance(payload, dict) else {}
        tpu = hw.get("tpu", {}) if isinstance(hw, dict) else {}
        devices = tpu.get("pixel_devices", []) if isinstance(tpu, dict) else []
        ip = ""
        if isinstance(devices, list) and devices:
            first = devices[0] if isinstance(devices[0], dict) else {}
            ip = str(first.get("ip") or first.get("id") or "").strip()
        summary = {
            "pixel_detected": bool(tpu.get("pixel_detected", False)),
            "pixel_count": int(tpu.get("pixel_count", 0) or 0),
            "pixel_ip": ip or None,
        }
        return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 180)
    if name in _WEB_LOOKUP_TOOL_NAMES:
        if isinstance(payload, dict) and str(payload.get("source", "")).strip() in {"wttr", "open_meteo"}:
            summary = {
                "location": payload.get("location"),
                "target_day": payload.get("target_day"),
                "date": payload.get("date"),
                "temp_min_c": payload.get("temp_min_c"),
                "temp_max_c": payload.get("temp_max_c"),
                "chance_of_rain_pct": payload.get("chance_of_rain_pct"),
                "summary": payload.get("summary"),
                "source": payload.get("source"),
            }
            return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 220)
        if isinstance(payload, dict) and str(payload.get("source", "")).strip() == "yahoo_finance":
            summary = {
                "name": payload.get("name"),
                "symbol": payload.get("symbol"),
                "price": payload.get("price"),
                "currency": payload.get("currency"),
                "change_percent": payload.get("change_percent"),
                "market_time_utc": payload.get("market_time_utc"),
                "source": "yahoo_finance",
            }
            return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 220)
        if isinstance(payload, dict) and str(payload.get("source", "")).strip() == "coingecko":
            summary = {
                "asset": payload.get("asset"),
                "price_eur": payload.get("price_eur"),
                "price_usd": payload.get("price_usd"),
                "last_updated_at": payload.get("last_updated_at"),
                "source": "coingecko",
            }
            return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 200)
        if isinstance(payload, dict) and str(payload.get("source", "")).strip() == "wikipedia":
            summary = {
                "title": payload.get("title"),
                "description": payload.get("summary"),
                "url": payload.get("url"),
                "source": "wikipedia",
            }
            return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 240)
        rss_head = _extract_bing_rss_head(payload)
        if rss_head:
            rss_items = _extract_bing_rss_candidates(payload, limit=3)
            compact_items = []
            for item in rss_items:
                compact_items.append(
                    {
                        "title": item.get("title"),
                        "description": item.get("description"),
                        "url": item.get("link"),
                        "published_at": item.get("pub_date"),
                    }
                )
            summary = {"items": compact_items or [rss_head]}
            return _clip_memory_text(json.dumps(summary, ensure_ascii=False), 220)
        raw = str(payload.get("raw", "")).strip()
        if raw:
            return _clip_memory_text(raw.replace("\n", " "), 220)
    return _clip_memory_text(json.dumps(payload, ensure_ascii=False), 180)


def _collect_tool_context(prompt: str, timeout_s: float) -> tuple[str, list[dict[str, Any]]]:
    tools = _load_picobot_config_tools()
    if not tools:
        return "", []
    enabled_tools = [tool for tool in tools if bool(tool.get("enabled", True))]
    if not enabled_tools:
        return "", []
    selected: list[dict[str, Any]] = []

    planner_result = _plan_tools_with_openai(
        prompt=prompt,
        tools=enabled_tools,
        timeout_s=min(float(timeout_s), OPENAI_PLANNER_TIMEOUT_S),
    )
    with _STATE_LOCK:
        _STATE["planner_calls"] = int(_STATE.get("planner_calls", 0) or 0) + 1
    if isinstance(planner_result, dict):
        selected_names = planner_result.get("tools", [])
        if isinstance(selected_names, list) and selected_names:
            names_set = {str(item).strip() for item in selected_names if str(item).strip()}
            selected = [
                tool
                for tool in enabled_tools
                if str(tool.get("name", "")).strip() in names_set
            ]
        with _STATE_LOCK:
            _STATE["planner_success"] = int(_STATE.get("planner_success", 0) or 0) + 1
            _STATE["planner_last"] = _clip_memory_text(
                json.dumps(planner_result, ensure_ascii=False),
                180,
            )
        answer_mode = str(planner_result.get("answer_mode", "")).strip().lower()
        if not selected and answer_mode in {"llm_only", "none"}:
            return "", []

    if not selected:
        for tool in enabled_tools:
            if _tool_matches_prompt(str(tool.get("name", "")), prompt):
                selected.append(tool)
    if not selected:
        return "", []

    effective_timeout = _bounded_timeout(
        min(timeout_s, PICOBOT_TOOL_TIMEOUT_MAX_S),
        default=1.2,
        upper=PICOBOT_TOOL_TIMEOUT_MAX_S,
    )
    lines: list[str] = []
    reports: list[dict[str, Any]] = []

    def _exec_tool(index: int, tool: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        name = str(tool.get("name", "")).strip() or "tool"
        tool_timeout = _bounded_timeout(
            tool.get("timeout_seconds", effective_timeout),
            default=effective_timeout,
            upper=PICOBOT_TOOL_TIMEOUT_MAX_S,
        )
        ok, result = _call_http_tool(tool, tool_timeout, prompt=prompt)
        report = {"name": name, "ok": bool(ok), "result": result}
        return index, report

    indexed_reports: list[tuple[int, dict[str, Any]]] = []
    if len(selected) <= 1:
        indexed_reports = [_exec_tool(0, selected[0])]
    else:
        max_workers = max(2, min(4, len(selected)))
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="didier-tools") as pool:
            futures = [
                pool.submit(_exec_tool, idx, tool)
                for idx, tool in enumerate(selected)
            ]
            for future in futures:
                try:
                    indexed_reports.append(future.result())
                except Exception as exc:
                    indexed_reports.append(
                        (
                            len(indexed_reports),
                            {
                                "name": "tool",
                                "ok": False,
                                "result": {"error": f"tool_executor_failed:{exc}"},
                            },
                        )
                    )
    indexed_reports.sort(key=lambda item: int(item[0]))
    for _, report in indexed_reports:
        reports.append(report)
        name = str(report.get("name", "tool")).strip() or "tool"
        if bool(report.get("ok", False)):
            short = _summarize_tool_result(name, report.get("result", {}))
            lines.append(f"- {name}: {short}")
        else:
            err = _clip_memory_text(json.dumps(report.get("result", {}), ensure_ascii=False), 180)
            lines.append(f"- {name}: erreur={err}")
    with _STATE_LOCK:
        _STATE["tool_calls"] = int(_STATE.get("tool_calls", 0) or 0) + len(selected)
        failures = sum(1 for item in reports if not bool(item.get("ok", False)))
        _STATE["tool_failures"] = int(_STATE.get("tool_failures", 0) or 0) + failures
        _STATE["tool_last_names"] = [str(item.get("name", "")) for item in reports][:6]
        if failures:
            _STATE["tool_last_error"] = _clip_memory_text(json.dumps(reports, ensure_ascii=False), 180)
        else:
            _STATE["tool_last_error"] = ""
    if not lines:
        return "", reports
    return "Contexte outils Didier (temps reel):\n" + "\n".join(lines), reports


def _build_tool_only_response(prompt: str, tool_reports: list[dict[str, Any]]) -> str:
    by_name: dict[str, dict[str, Any]] = {}
    generic_web_requires_llm = False
    for item in tool_reports:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        by_name[name] = item

    parts: list[str] = []
    health = by_name.get("get_system_status")
    if isinstance(health, dict) and bool(health.get("ok", False)):
        payload = health.get("result", {}).get("payload", {}) if isinstance(health.get("result"), dict) else {}
        if isinstance(payload, dict):
            status = str(payload.get("status", "unknown")).strip()
            name = str(payload.get("name", "Didier")).strip() or "Didier"
            parts.append(f"Statut {name}: {status}.")

    camera = by_name.get("check_camera")
    if isinstance(camera, dict) and bool(camera.get("ok", False)):
        payload = camera.get("result", {}).get("payload", {}) if isinstance(camera.get("result"), dict) else {}
        if isinstance(payload, dict):
            ready = bool(payload.get("ready", False))
            detector = str(payload.get("detector", "inconnu")).strip() or "inconnu"
            last_count = payload.get("last_count", None)
            if ready:
                parts.append(f"Camera: active (detecteur {detector}, objets detectes: {last_count if last_count is not None else 0}).")
            else:
                parts.append("Camera: indisponible.")

    pixel = by_name.get("get_pixel_status")
    if isinstance(pixel, dict) and bool(pixel.get("ok", False)):
        payload = pixel.get("result", {}).get("payload", {}) if isinstance(pixel.get("result"), dict) else {}
        hw = payload.get("hardware_profile", {}) if isinstance(payload, dict) else {}
        tpu = hw.get("tpu", {}) if isinstance(hw, dict) else {}
        pixel_detected = bool(tpu.get("pixel_detected", False))
        pixel_count = int(tpu.get("pixel_count", 0) or 0)
        devices = tpu.get("pixel_devices", []) if isinstance(tpu, dict) else []
        pixel_ip = ""
        if isinstance(devices, list) and devices:
            first = devices[0] if isinstance(devices[0], dict) else {}
            pixel_ip = str(first.get("ip") or first.get("id") or "").strip()
        if pixel_detected:
            if pixel_ip:
                parts.append(f"Pixel: detecte et joignable sur {pixel_ip} (instances: {pixel_count}).")
            else:
                parts.append(f"Pixel: detecte (instances: {pixel_count}).")
        else:
            parts.append("Pixel: non detecte actuellement.")

    web_report: dict[str, Any] | None = None
    for web_name in _WEB_LOOKUP_TOOL_NAMES:
        candidate = by_name.get(web_name)
        if isinstance(candidate, dict):
            web_report = candidate
            break
    if isinstance(web_report, dict) and bool(web_report.get("ok", False)):
        payload = (
            web_report.get("result", {}).get("payload", {})
            if isinstance(web_report.get("result"), dict)
            else {}
        )
        if isinstance(payload, dict) and str(payload.get("source", "")).strip() in {"wttr", "open_meteo"}:
            location = str(payload.get("location", "")).strip() or "la zone demandee"
            target_day = str(payload.get("target_day", "")).strip() or "aujourd'hui"
            date = str(payload.get("date", "")).strip()
            tmin = payload.get("temp_min_c")
            tmax = payload.get("temp_max_c")
            rain = payload.get("chance_of_rain_pct")
            summary = str(payload.get("summary", "")).strip()
            temp_parts: list[str] = []
            if tmin not in (None, ""):
                temp_parts.append(f"min {tmin}°C")
            if tmax not in (None, ""):
                temp_parts.append(f"max {tmax}°C")
            sentence = f"Meteo {target_day} a {location}"
            if date:
                sentence += f" ({date})"
            sentence += ": "
            if summary:
                sentence += summary
            if temp_parts:
                sentence += ("; " if summary else "") + ", ".join(temp_parts)
            if rain not in (None, ""):
                sentence += f"; pluie {rain}%"
            parts.append(sentence.strip().rstrip(";") + ".")
        elif isinstance(payload, dict) and str(payload.get("source", "")).strip() == "yahoo_finance":
            name = str(payload.get("name", "")).strip()
            symbol = str(payload.get("symbol", "")).strip()
            price = payload.get("price")
            currency = str(payload.get("currency", "")).strip() or ""
            change_pct = payload.get("change_percent")
            market_time = str(payload.get("market_time_utc", "")).strip()
            if price not in (None, ""):
                label = name or symbol or "valeur"
                text = f"{label}: {price} {currency}".strip()
                if change_pct not in (None, ""):
                    if isinstance(change_pct, (float, int)):
                        text += f" ({change_pct:+.2f}%)"
                    else:
                        text += f" ({change_pct}%)"
                text += "."
                if market_time:
                    text += f" Derniere mise a jour: {market_time}."
                parts.append(text)
        elif isinstance(payload, dict) and str(payload.get("source", "")).strip() == "coingecko":
            asset = str(payload.get("asset", "crypto")).strip() or "crypto"
            eur = payload.get("price_eur")
            usd = payload.get("price_usd")
            updated_at = payload.get("last_updated_at")
            value_parts: list[str] = []
            if eur is not None:
                value_parts.append(f"{eur} EUR")
            if usd is not None:
                value_parts.append(f"{usd} USD")
            if value_parts:
                text = f"Prix {asset}: " + " / ".join(value_parts) + "."
                if updated_at:
                    text += f" Update epoch: {updated_at}."
                parts.append(text)
        elif isinstance(payload, dict) and str(payload.get("source", "")).strip() == "wikipedia":
            title = str(payload.get("title", "")).strip()
            description = str(payload.get("summary", "")).strip()
            message = description or title
            if message and title and title.lower() not in message.lower():
                message = f"{title}. {message}"
            message = _clip_memory_text(message, 240)
            if message:
                parts.append(message if message.endswith((".", "!", "?")) else f"{message}.")
        else:
            # Generic RSS/web snippets are too noisy for direct user output.
            # Keep them in tool context and force LLM synthesis.
            generic_web_requires_llm = True

    if not parts:
        return ""
    # For generic RSS/web snippets, prefer LLM synthesis rather than raw snippets.
    if generic_web_requires_llm:
        return ""
    return " ".join(parts).strip()


def _react_via_openai_compat(prompt: str, timeout_s: float, tool_context: str = "") -> dict[str, Any]:
    llm = _load_picobot_llm_settings()
    base_url = str(llm.get("base_url", "")).strip().rstrip("/")
    model = str(llm.get("model", "")).strip()
    system_prompt = str(llm.get("system_prompt", "")).strip()
    if not base_url:
        return {"ok": False, "error": "openai_compat base_url missing"}
    if not model:
        return {"ok": False, "error": "openai_compat model missing"}

    try:
        request_timeout_s = float(timeout_s)
    except Exception:
        request_timeout_s = DEFAULT_TIMEOUT_S
    budget_timeout_s = max(0.6, request_timeout_s - 0.25)
    effective_timeout_s = max(0.5, min(OPENAI_COMPAT_TIMEOUT_S, budget_timeout_s))

    context_block = str(tool_context or "").strip()
    user_prompt_parts: list[str] = []
    if context_block:
        user_prompt_parts.append(context_block)
    user_prompt_parts.append("Question utilisateur:\n" + f"{str(prompt or '').strip()}")
    user_prompt_parts.append(
        "Consignes:\n"
        "- reponds en francais\n"
        "- reponse concise et actionable (2 phrases max)\n"
        "- utilise les donnees des outils si presentes\n"
        "- ne renvoie pas de details techniques (routes, logs, endpoint), sauf demande explicite\n"
        "- si l'information manque, excuse-toi et donne la raison en une phrase"
    )
    user_prompt = "\n\n".join(user_prompt_parts)
    base_messages: list[dict[str, str]] = []
    if system_prompt:
        base_messages.append({"role": "system", "content": system_prompt})
    base_messages.append({"role": "user", "content": user_prompt})
    first = _openai_chat_request(
        llm_settings=llm,
        messages=base_messages,
        timeout_s=effective_timeout_s,
        max_tokens=180,
        temperature=0.15,
        cache_namespace="react",
        use_cache=True,
    )
    if not first.get("ok", False):
        return first
    reply = str(first.get("response", "")).strip()
    if _contains_non_latin_response(reply):
        strict_prompt_parts: list[str] = []
        if context_block:
            strict_prompt_parts.append(context_block)
        strict_prompt_parts.append("Question utilisateur:\n" + f"{str(prompt or '').strip()}")
        strict_prompt_parts.append(
            "Consignes strictes:\n"
            "- reponds uniquement en francais (alphabet latin)\n"
            "- pas de chinois ni d'autres ecritures\n"
            "- 2 phrases max"
        )
        strict_messages: list[dict[str, str]] = []
        if system_prompt:
            strict_messages.append({"role": "system", "content": system_prompt})
        strict_messages.append({"role": "user", "content": "\n\n".join(strict_prompt_parts)})
        retry_timeout_s = max(0.6, min(2.2, effective_timeout_s * 0.55))
        retry = _openai_chat_request(
            llm_settings=llm,
            messages=strict_messages,
            timeout_s=retry_timeout_s,
            max_tokens=140,
            temperature=0.0,
            cache_namespace="react_strict",
            use_cache=False,
        )
        if retry.get("ok", False):
            retry_reply = str(retry.get("response", "")).strip()
            if retry_reply and not _contains_non_latin_response(retry_reply):
                reply = retry_reply
        if _contains_non_latin_response(reply):
            return {"ok": False, "error": "openai_compat non_latin_response"}
    return {
        "ok": True,
        "response": reply,
        "source": "openai_compat",
        "model": model,
        "endpoint": f"{base_url}/chat/completions",
        "probe": "skipped",
        "cached": bool(first.get("cached", False)),
    }


def _humanize_failure_reason(error: Any) -> str:
    text = str(error or "").strip()
    if not text:
        return "raison inconnue"
    normalized = text.lower()
    if "timeout" in normalized or "timed out" in normalized:
        return "delai depasse vers le cerveau distant"
    if (
        "connection refused" in normalized
        or "failed to establish a new connection" in normalized
        or "name or service not known" in normalized
        or "nodename nor servname provided" in normalized
        or "no route to host" in normalized
    ):
        return "connexion au cerveau distant indisponible"
    if "http 401" in normalized or "http 403" in normalized:
        return "acces refuse par le service LLM"
    if "http 404" in normalized:
        return "endpoint LLM introuvable"
    if "empty response" in normalized:
        return "le modele ne renvoie aucune reponse"
    if "invalid_json" in normalized or "invalid payload" in normalized:
        return "reponse invalide du service distant"
    if "base_url missing" in normalized:
        return "configuration LLM incomplete (base_url absente)"
    if "model missing" in normalized:
        return "configuration LLM incomplete (modele absent)"
    return _clip_memory_text(text, 120)


def _build_user_apology(reason: Any) -> str:
    reason_text = _humanize_failure_reason(reason)
    return f"Desole, je ne peux pas traiter ta demande pour le moment: {reason_text}."


def _normalize_task_type(value: Any, default: str = "chat") -> str:
    task_type = str(value or "").strip().lower()
    if not task_type:
        task_type = default
    return task_type


def _fallback_routing(prompt: str, task_type: str, reason: str) -> dict[str, Any]:
    normalized = _normalize_task_type(task_type, default="chat")
    is_react = normalized == "react_task"
    if is_react:
        preferred = "picobot_bridge"
        execution = "picobot_bridge"
        route_hint = "picobot_bridge"
        priority_reason = "task_orchestration_picobot"
    else:
        preferred = "local_ollama"
        execution = "local_ollama"
        route_hint = "brain_local"
        priority_reason = "fallback_local"
    return {
        "task_type": normalized,
        "preferred_backend": preferred,
        "execution_backend": execution,
        "route_hint": route_hint,
        "priority_reason": priority_reason,
        "recommended_model": "",
        "recommendation_source": "fallback",
        "recommendation_reason": str(reason or "routing unavailable"),
        "provider": "llmfit",
        "score": "good",
        "fallback_active": False,
        "pixel_detected": False,
        "pixel_count": 0,
        "npu_available": False,
        "npu_device_count": 0,
        "prompt_preview": str(prompt or "")[:120],
    }


def _compute_routing(
    prompt: str,
    task_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = _normalize_task_type(task_type, default="chat")
    if choose_backend_contract is None:
        return _fallback_routing(
            prompt,
            normalized,
            f"backend routing module unavailable: {_ROUTING_IMPORT_ERROR or 'unknown'}",
        )

    context: dict[str, Any] = {}
    if isinstance(payload, dict):
        raw_context = payload.get("context", {})
        if isinstance(raw_context, dict):
            context.update(raw_context)
        for key in ("is_voice", "force_task", "source", "caller"):
            if key in payload:
                context[key] = payload.get(key)
    context.setdefault("bridge", "picobot")
    context.setdefault("prompt_preview", str(prompt or "")[:120])

    try:
        result = choose_backend_contract(
            str(prompt or ""),
            normalized,
            context=context,
        )
        if isinstance(result, dict):
            return dict(result)
        return _fallback_routing(prompt, normalized, "invalid routing payload")
    except Exception as exc:
        return _fallback_routing(prompt, normalized, f"routing error: {exc}")


def _react_via_picobot(prompt: str, timeout_s: float) -> dict[str, Any]:
    tool_context, tool_reports = _collect_tool_context(prompt, timeout_s)
    tool_only_response = _build_tool_only_response(prompt, tool_reports)
    if tool_only_response:
        return {
            "ok": True,
            "response": tool_only_response,
            "source": "picobot_bridge_tools_only",
            "tool_reports": tool_reports,
        }
    if not _cli_mode_uses_cli():
        fallback = _react_via_openai_compat(prompt, timeout_s, tool_context=tool_context)
        if fallback.get("ok", False):
            fallback["degraded"] = True
            fallback["source"] = "picobot_bridge_openai_tools"
            if tool_reports:
                fallback["tool_reports"] = tool_reports
            return fallback
        with _STATE_LOCK:
            _STATE["openai_fallback_failures"] = int(_STATE.get("openai_fallback_failures", 0) or 0) + 1
        fallback_error = str(fallback.get("error", "unknown"))
        return {
            "ok": True,
            "degraded": True,
            "response": _build_user_apology(fallback_error),
            "source": "picobot_bridge_openai_unavailable",
            "openai_fallback_error": fallback_error,
            "failure_reason": _humanize_failure_reason(fallback_error),
            "tool_reports": tool_reports,
        }

    cmd = [
        "docker",
        "exec",
        "-e",
        f"HOME={PICOBOT_RUNTIME_HOME}",
        PICOBOT_CONTAINER,
        "picobot",
        "agent",
        "-m",
        prompt,
    ]
    env = os.environ.copy()
    env.setdefault("HOME", PICOBOT_RUNTIME_HOME)
    try:
        proc = _run_command(cmd, timeout_s, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"picobot agent timeout after {timeout_s:.1f}s"}
    except Exception as exc:
        return {"ok": False, "error": f"picobot agent exec failed: {exc}"}

    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
        return {"ok": False, "error": detail[:300]}

    raw = str(proc.stdout or "").strip()
    stderr = str(proc.stderr or "").strip()
    if stderr and ("error:" in stderr.lower() or "openai api" in stderr.lower()):
        return {"ok": False, "error": stderr[:300], "raw": raw}
    reply = _extract_reply(raw)
    if not reply:
        return {"ok": False, "error": "picobot returned empty response", "raw": raw, "stderr": stderr[:300]}
    if _is_stub_reply(reply):
        with _STATE_LOCK:
            _STATE["stub_responses"] = int(_STATE.get("stub_responses", 0) or 0) + 1
            _STATE["openai_fallback_calls"] = int(_STATE.get("openai_fallback_calls", 0) or 0) + 1
            if PICOBOT_CLI_MODE == "auto" and int(_STATE.get("stub_responses", 0) or 0) >= 2:
                _STATE["cli_disabled_due_stub"] = True
        fallback = _react_via_openai_compat(prompt, timeout_s, tool_context=tool_context)
        if fallback.get("ok", False):
            fallback["degraded"] = True
            fallback["picobot_stub"] = reply
            fallback["raw"] = raw
            fallback["source"] = "picobot_stub_openai_fallback"
            if tool_reports:
                fallback["tool_reports"] = tool_reports
            return fallback
        with _STATE_LOCK:
            _STATE["openai_fallback_failures"] = int(_STATE.get("openai_fallback_failures", 0) or 0) + 1
        fallback_error = str(fallback.get("error", "unknown"))
        return {
            "ok": True,
            "degraded": True,
            "response": _build_user_apology(fallback_error),
            "raw": raw,
            "source": "picobot_stub_unavailable",
            "openai_fallback_error": fallback_error,
            "failure_reason": _humanize_failure_reason(fallback_error),
            "tool_reports": tool_reports,
        }
    result = {"ok": True, "response": reply, "raw": raw, "source": "picobot_cli"}
    if tool_reports:
        result["tool_reports"] = tool_reports
    return result


def _memory_sources(include_content: bool) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    today_key = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for rel in (
        "config.json",
        "workspace/memory/LONG_TERM.md",
        "workspace/memory/TODAY.md",
        f"workspace/memory/history/{today_key}.md",
        "workspace/HEARTBEAT.md",
    ):
        path = PICOBOT_DATA_DIR / rel
        if not path.exists() or not path.is_file():
            continue
        item: dict[str, Any] = {
            "path": str(path),
            "exists": True,
            "size": int(path.stat().st_size),
            "mtime": float(path.stat().st_mtime),
        }
        if include_content:
            try:
                item["content"] = path.read_text(encoding="utf-8")
            except Exception:
                item["content"] = ""
        sources.append(item)
    return sources


def _safe_join_memory_path(path: str) -> Path:
    rel = str(path or "").strip()
    if not rel:
        raise ValueError("path required")
    candidate = (PICOBOT_DATA_DIR / rel).resolve()
    root = PICOBOT_DATA_DIR.resolve()
    if not str(candidate).startswith(str(root)):
        raise ValueError("path outside picobot_data")
    return candidate


def _update_react_stats(ok: bool, elapsed_ms: float, error: str = "") -> None:
    with _STATE_LOCK:
        _STATE["last_react_ts"] = time.time()
        _STATE["last_react_ms"] = round(float(elapsed_ms), 2)
        _STATE["react_calls"] = int(_STATE.get("react_calls", 0) or 0) + 1
        if not ok:
            _STATE["react_failures"] = int(_STATE.get("react_failures", 0) or 0) + 1
            _STATE["last_error"] = str(error or "")


def _clip_memory_text(value: Any, limit: int = MEMORY_TEXT_LIMIT) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _trim_file_tail(path: Path, max_bytes: int, keep_bytes: int) -> None:
    try:
        size = int(path.stat().st_size)
    except Exception:
        return
    if size <= max_bytes:
        return
    try:
        with path.open("rb") as fh:
            if size > keep_bytes:
                fh.seek(size - keep_bytes)
            data = fh.read()
        text = data.decode("utf-8", errors="ignore")
        first_newline = text.find("\n")
        if first_newline >= 0:
            text = text[first_newline + 1 :]
        trimmed = (
            "# Picobot rolling memory\n"
            "_Old entries trimmed automatically to keep runtime stable._\n\n"
            f"{text.lstrip()}"
        )
        path.write_text(trimmed, encoding="utf-8")
    except Exception:
        return


def _ensure_memory_layout() -> None:
    MEMORY_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    if not MEMORY_TODAY_PATH.exists():
        MEMORY_TODAY_PATH.write_text(
            "# TODAY\n"
            "_Continuous memory generated by didier-picobot bridge._\n\n",
            encoding="utf-8",
        )
    if not MEMORY_LONG_TERM_PATH.exists():
        MEMORY_LONG_TERM_PATH.write_text(
            "# LONG_TERM\n"
            "_Pin durable facts here._\n\n",
            encoding="utf-8",
        )
    if not MEMORY_HEARTBEAT_PATH.exists():
        MEMORY_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        MEMORY_HEARTBEAT_PATH.write_text(
            "# HEARTBEAT\n"
            "_Picobot memory heartbeat._\n\n",
            encoding="utf-8",
        )


try:
    _ensure_memory_layout()
except Exception:
    pass


def _memory_status_update(ok: bool, error: str = "") -> None:
    with _STATE_LOCK:
        if ok:
            _STATE["memory_last_write_ts"] = time.time()
            _STATE["memory_last_error"] = ""
        else:
            _STATE["memory_write_failures"] = int(_STATE.get("memory_write_failures", 0) or 0) + 1
            _STATE["memory_last_error"] = str(error or "")[:200]


def _persist_continuous_memory(
    prompt: str,
    response: str,
    routing: dict[str, Any] | None,
    task_type: str,
    ok: bool,
    degraded: bool,
    error: str = "",
    elapsed_ms: float = 0.0,
) -> None:
    ts = datetime.now(timezone.utc)
    ts_iso = ts.isoformat(timespec="seconds")
    day_key = ts.strftime("%Y-%m-%d")

    route = routing or {}
    route_hint = _clip_memory_text(route.get("route_hint", ""))
    exec_backend = _clip_memory_text(route.get("execution_backend", ""))
    model = _clip_memory_text(route.get("recommended_model", ""))
    task = _clip_memory_text(task_type, 40) or "react_task"
    prompt_line = _clip_memory_text(prompt, MEMORY_TEXT_LIMIT)
    response_line = _clip_memory_text(response, MEMORY_TEXT_LIMIT)
    error_line = _clip_memory_text(error, MEMORY_TEXT_LIMIT)
    latency = round(float(elapsed_ms or 0.0), 2)

    lines = [
        f"### {ts_iso} | task={task} | ok={str(bool(ok)).lower()} | degraded={str(bool(degraded)).lower()}",
        f"- route: {route_hint or '-'}",
        f"- backend: {exec_backend or '-'}",
        f"- model: {model or '-'}",
        f"- latency_ms: {latency}",
        f"- prompt: {prompt_line or '-'}",
        f"- response: {response_line or '-'}",
    ]
    if error_line:
        lines.append(f"- error: {error_line}")
    entry = "\n".join(lines) + "\n\n"
    daily_path = MEMORY_HISTORY_DIR / f"{day_key}.md"

    try:
        with _MEMORY_LOCK:
            _ensure_memory_layout()
            with MEMORY_TODAY_PATH.open("a", encoding="utf-8") as fh:
                fh.write(entry)
            with daily_path.open("a", encoding="utf-8") as fh:
                fh.write(entry)
            heartbeat = (
                f"last_update_utc: {ts_iso}\n"
                f"last_task: {task}\n"
                f"last_ok: {str(bool(ok)).lower()}\n"
                f"last_degraded: {str(bool(degraded)).lower()}\n"
                f"last_route: {route_hint or '-'}\n"
                f"last_backend: {exec_backend or '-'}\n"
            )
            MEMORY_HEARTBEAT_PATH.write_text(heartbeat, encoding="utf-8")
            _trim_file_tail(MEMORY_TODAY_PATH, MEMORY_FILE_LIMIT_BYTES, MEMORY_FILE_TRIM_BYTES)
            _trim_file_tail(daily_path, MEMORY_FILE_LIMIT_BYTES, MEMORY_FILE_TRIM_BYTES)
        _memory_status_update(True)
    except Exception as exc:
        _memory_status_update(False, str(exc))


@app.get("/health")
async def health() -> dict[str, Any]:
    running, detail = await asyncio.to_thread(_container_running)
    with _STATE_LOCK:
        stats = dict(_STATE)
    return {
        "status": "ok" if running else "degraded",
        "service": "didier-picobot",
        "bridge": "didier-picobot-bridge",
        "container": PICOBOT_CONTAINER,
        "container_running": running,
        "detail": detail,
        "uptime_s": round(time.time() - float(stats.get("started_at", time.time())), 2),
        "stats": stats,
        "ts": time.time(),
    }


@app.post("/react")
@app.post("/agent/react")
@app.post("/v1/agent/react")
async def react(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    prompt = str(
        payload.get("prompt")
        or payload.get("text")
        or payload.get("message")
        or ""
    ).strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    task_type = _normalize_task_type(payload.get("task_type", "react_task"), default="react_task")
    routing = await asyncio.to_thread(_compute_routing, prompt, task_type, payload)

    if task_type != "react_task" and str(routing.get("preferred_backend", "")) != "picobot_bridge":
        result = {
            "ok": True,
            "delegated": True,
            "source": "picobot_bridge_router",
            "detail": f"delegated:{routing.get('execution_backend', 'local_ollama')}",
            "routing": routing,
            "task_type": task_type,
            "ts": time.time(),
        }
        await asyncio.to_thread(
            _persist_continuous_memory,
            prompt,
            str(result.get("detail", "delegated")),
            routing,
            task_type,
            True,
            False,
            "",
            0.0,
        )
        return result

    timeout_s = _bounded_timeout(
        payload.get("timeout_s", payload.get("react_timeout_s", REACT_TIMEOUT_DEFAULT_S)),
        REACT_TIMEOUT_DEFAULT_S,
        REACT_TIMEOUT_MAX_S,
    )
    running, detail = await asyncio.to_thread(_container_running)
    if not running:
        result = {
            "ok": False,
            "error": f"picobot container unavailable: {detail}",
            "routing": routing,
            "task_type": task_type,
        }
        _update_react_stats(False, 0.0, result["error"])
        await asyncio.to_thread(
            _persist_continuous_memory,
            prompt,
            "",
            routing,
            task_type,
            False,
            True,
            str(result.get("error", "")),
            0.0,
        )
        return result

    started = time.perf_counter()
    picobot_result = await asyncio.to_thread(_react_via_picobot, prompt, timeout_s)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if picobot_result.get("ok", False):
        _update_react_stats(True, elapsed_ms)
        picobot_result["elapsed_ms"] = round(elapsed_ms, 2)
        picobot_result["container"] = PICOBOT_CONTAINER
        picobot_result["timeout_s"] = timeout_s
        picobot_result["routing"] = routing
        picobot_result["task_type"] = task_type
        await asyncio.to_thread(
            _persist_continuous_memory,
            prompt,
            str(picobot_result.get("response", "")),
            routing,
            task_type,
            True,
            False,
            "",
            elapsed_ms,
        )
        return picobot_result

    elapsed_ms = (time.perf_counter() - started) * 1000.0
    error = f"picobot failed: {picobot_result.get('error', 'unknown')}"
    _update_react_stats(False, elapsed_ms, error)
    fallback_text = _build_user_apology(error)
    result = {
        "ok": True,
        "response": fallback_text,
        "source": "picobot_bridge_fallback",
        "degraded": True,
        "picobot_error": error,
        "failure_reason": _humanize_failure_reason(error),
        "elapsed_ms": round(elapsed_ms, 2),
        "container": PICOBOT_CONTAINER,
        "timeout_s": timeout_s,
        "routing": routing,
        "task_type": task_type,
    }
    await asyncio.to_thread(
        _persist_continuous_memory,
        prompt,
        fallback_text,
        routing,
        task_type,
        True,
        True,
        error,
        elapsed_ms,
    )
    return result


@app.post("/route")
@app.post("/agent/route")
@app.post("/v1/agent/route")
async def route_post(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    prompt = str(
        payload.get("prompt")
        or payload.get("text")
        or payload.get("message")
        or ""
    ).strip()
    task_type = _normalize_task_type(payload.get("task_type", "chat"), default="chat")
    routing = await asyncio.to_thread(_compute_routing, prompt, task_type, payload)
    return {
        "ok": True,
        "service": "didier-picobot",
        "bridge": "didier-picobot-bridge",
        "task_type": task_type,
        "prompt_preview": prompt[:120],
        "routing": routing,
        "ts": time.time(),
    }


@app.get("/route")
@app.get("/agent/route")
async def route_get(prompt: str = "", task_type: str = "chat") -> dict[str, Any]:
    prompt_text = str(prompt or "").strip()
    normalized = _normalize_task_type(task_type, default="chat")
    routing = await asyncio.to_thread(_compute_routing, prompt_text, normalized, {})
    return {
        "ok": True,
        "service": "didier-picobot",
        "bridge": "didier-picobot-bridge",
        "task_type": normalized,
        "prompt_preview": prompt_text[:120],
        "routing": routing,
        "ts": time.time(),
    }


@app.get("/metrics")
@app.get("/agent/metrics")
async def metrics() -> dict[str, Any]:
    running, detail = await asyncio.to_thread(_container_running)
    with _STATE_LOCK:
        stats = dict(_STATE)
    return {
        "ok": True,
        "service": "didier-picobot",
        "bridge": "didier-picobot-bridge",
        "container": PICOBOT_CONTAINER,
        "running": running,
        "detail": detail,
        "stats": stats,
        "ts": time.time(),
    }


@app.get("/tools")
@app.get("/agent/tools")
async def tools(refresh: bool = False) -> dict[str, Any]:
    running, detail = await asyncio.to_thread(_container_running)
    payload = await asyncio.to_thread(_tools_snapshot, bool(refresh))
    return {
        "ok": True,
        "service": "didier-picobot",
        "bridge": "didier-picobot-bridge",
        "container": PICOBOT_CONTAINER,
        "running": running,
        "detail": detail,
        **payload,
    }


@app.get("/tasks")
@app.get("/agent/tasks")
async def tasks() -> dict[str, Any]:
    return {"ok": True, "tasks": [], "ts": time.time(), "service": "didier-picobot"}


@app.get("/memory")
@app.get("/agent/memory")
async def memory(include_content: bool = False) -> dict[str, Any]:
    include_content = bool(include_content)
    sources = await asyncio.to_thread(_memory_sources, include_content)
    return {
        "ok": True,
        "service": "didier-picobot",
        "memory": {"sources": sources, "root": str(PICOBOT_DATA_DIR)},
        "ts": time.time(),
    }


@app.post("/memory")
@app.post("/agent/memory")
async def memory_write(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = payload or {}
    path = str(payload.get("path", "")).strip()
    content = str(payload.get("content", ""))
    append = bool(payload.get("append", False))
    try:
        target = _safe_join_memory_path(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    target.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    try:
        with target.open(mode, encoding="utf-8") as fh:
            fh.write(content)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"memory write failed: {exc}") from exc
    return {
        "ok": True,
        "entry": {"path": str(target), "append": append, "size": int(target.stat().st_size)},
        "ts": time.time(),
        "service": "didier-picobot",
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=3901,
        log_level="info",
        access_log=False,
    )
