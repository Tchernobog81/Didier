from __future__ import annotations

import importlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

DEFAULT_TIMEOUT_S = 2.0
DEFAULT_PROVIDER = "llmfit"
DEFAULT_MODULE_NAME = "llmfit"
DEFAULT_CLI_BIN = "llmfit"
DEFAULT_CONFIG_PATH = Path("config/config.json")

DEFAULT_TASK_PROFILES: dict[str, dict[str, Any]] = {
    "chat": {
        "backend": "ollama",
        "model": "qwen2.5:1.5b",
        "score": "good",
        "reason": "fallback profile for conversation tasks",
    },
    "coding": {
        "backend": "ollama",
        "model": "qwen2.5-coder:1.5b",
        "score": "good",
        "reason": "fallback profile for coding tasks",
    },
    "vision": {
        "backend": "hailo",
        "model": "yolov8s_hailo8l.hef",
        "score": "good",
        "reason": "fallback profile for vision tasks",
    },
    "asr": {
        "backend": "asr-worker",
        "model": "whisper-small",
        "score": "good",
        "reason": "fallback profile for speech recognition tasks",
    },
    "tts": {
        "backend": "audio-worker",
        "model": "kokoro-v1.0.onnx",
        "score": "good",
        "reason": "fallback profile for speech synthesis tasks",
    },
}

TASK_ALIASES = {
    "conversation": "chat",
    "ask": "chat",
    "text": "chat",
    "code": "coding",
    "npu_inference": "vision",
    "detection": "vision",
    "speech_to_text": "asr",
    "stt": "asr",
    "text_to_speech": "tts",
}

DEFAULT_CLI_USE_CASES: dict[str, str] = {
    "chat": "chat",
    "coding": "coding",
    "vision": "multimodal",
    "asr": "chat",
    "tts": "chat",
    "react_task": "chat",
}


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return {str(k): v for k, v in value.items()}
    return {}


def _normalize_task_type(task_type: str) -> str:
    raw = str(task_type or "").strip().lower()
    if not raw:
        return "chat"
    return TASK_ALIASES.get(raw, raw)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _call_with_fallbacks(
    fn: Callable[..., Any],
    task_type: str,
    context: dict[str, Any],
) -> Any:
    attempts: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
        ((), {"task_type": task_type, "context": context}),
        ((), {"task": task_type, "context": context}),
        ((task_type, context), {}),
        ((task_type,), {}),
    )
    for args, kwargs in attempts:
        try:
            return fn(*args, **kwargs)
        except TypeError:
            continue
    raise TypeError("llmfit callable signature not supported by Didier wrapper")


class HardwareAwareRouter:
    """Thin llmfit wrapper with deterministic fallback profiles."""

    def __init__(self, config: Mapping[str, Any] | None = None) -> None:
        root = _as_mapping(config) or _read_json_file(DEFAULT_CONFIG_PATH)
        llmfit_cfg = _as_mapping(root.get("llmfit", {}))
        self._root = root
        self._cfg = llmfit_cfg
        self._logger = logging.getLogger("HardwareAware")
        self._enabled = _as_bool(llmfit_cfg.get("enabled", True), default=True)
        self._provider = str(llmfit_cfg.get("provider", DEFAULT_PROVIDER)).strip() or DEFAULT_PROVIDER
        python_cfg = _as_mapping(llmfit_cfg.get("python", {}))
        self._python_enabled = _as_bool(python_cfg.get("enabled", True), default=True)
        self._module_name = str(python_cfg.get("module", DEFAULT_MODULE_NAME)).strip() or DEFAULT_MODULE_NAME
        cli_cfg = _as_mapping(llmfit_cfg.get("cli", {}))
        self._cli_enabled = _as_bool(cli_cfg.get("enabled", True), default=True)
        self._cli_command = str(cli_cfg.get("command", DEFAULT_CLI_BIN)).strip() or DEFAULT_CLI_BIN
        self._cli_limit = max(1, min(_as_int(cli_cfg.get("limit", 3), 3), 20))
        self._cli_use_cases = dict(DEFAULT_CLI_USE_CASES)
        cli_use_cases = _as_mapping(cli_cfg.get("use_case_map", {}))
        for task_name, use_case in cli_use_cases.items():
            normalized_task = _normalize_task_type(task_name)
            use_case_name = str(use_case or "").strip().lower()
            if use_case_name:
                self._cli_use_cases[normalized_task] = use_case_name
        self._timeout_s = max(
            0.1,
            min(_as_float(llmfit_cfg.get("timeout_seconds", DEFAULT_TIMEOUT_S), DEFAULT_TIMEOUT_S), DEFAULT_TIMEOUT_S),
        )
        task_profiles = _as_mapping(llmfit_cfg.get("task_profiles", {}))
        self._task_profiles: dict[str, dict[str, Any]] = {
            key: _as_mapping(value) for key, value in task_profiles.items()
        }
        self._allowlists: dict[str, list[str]] = {}
        raw_allowlists = _as_mapping(llmfit_cfg.get("allowed_models", {}))
        for key, value in raw_allowlists.items():
            if isinstance(value, list):
                self._allowlists[key] = [str(item).strip() for item in value if str(item).strip()]

        self._module_lock = threading.Lock()
        self._module_obj: Any = None
        self._module_error: str | None = None
        self._module_loaded = False

    def _load_llmfit_module(self) -> tuple[Any | None, str | None]:
        if not self._enabled:
            return None, "llmfit disabled by config"
        if not self._python_enabled:
            return None, "python llmfit adapter disabled by config"
        with self._module_lock:
            if self._module_loaded:
                return self._module_obj, self._module_error
            try:
                self._module_obj = importlib.import_module(self._module_name)
                self._module_error = None
            except Exception as exc:
                self._module_obj = None
                self._module_error = f"{type(exc).__name__}: {exc}"
            self._module_loaded = True
            return self._module_obj, self._module_error

    def _resolve_cli_bin(self) -> str | None:
        candidate = os.path.expanduser(str(self._cli_command or "").strip())
        if not candidate:
            return None
        if "/" in candidate:
            path = Path(candidate)
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
            return None
        located = shutil.which(candidate)
        if located:
            return located
        fallback_paths = (
            Path.home() / ".local" / "bin" / candidate,
            Path("/usr/local/bin") / candidate,
            Path("/usr/bin") / candidate,
            Path("/bin") / candidate,
        )
        for path in fallback_paths:
            if path.is_file() and os.access(path, os.X_OK):
                return str(path)
        return None

    def _recommend_from_cli(
        self,
        task_type: str,
        context: Mapping[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str | None]:
        if not self._enabled:
            return None, "llmfit disabled by config"
        if not self._cli_enabled:
            return None, "llmfit cli adapter disabled by config"
        binary = self._resolve_cli_bin()
        if not binary:
            return None, f"llmfit binary `{self._cli_command}` not found"
        normalized = _normalize_task_type(task_type)
        use_case = self._cli_use_cases.get(normalized, "")
        command: list[str] = [binary, "recommend", "--json", "--limit", str(self._cli_limit)]
        if use_case:
            command.extend(["--use-case", use_case])
        try:
            proc = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return None, f"llmfit cli timeout after {self._timeout_s:.1f}s"
        except Exception as exc:
            return None, f"llmfit cli execution failed: {type(exc).__name__}: {exc}"
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or f"exit {proc.returncode}").strip()
            return None, f"llmfit cli error: {detail[:180]}"
        raw = str(proc.stdout or "").strip()
        if not raw:
            return None, "llmfit cli returned empty output"
        try:
            payload = json.loads(raw)
        except Exception as exc:
            return None, f"llmfit cli returned invalid json: {type(exc).__name__}: {exc}"
        if not isinstance(payload, Mapping):
            return None, "llmfit cli json payload is not an object"
        models = payload.get("models")
        if not isinstance(models, list) or not models:
            return None, "llmfit cli returned no model recommendations"
        top = models[0]
        if not isinstance(top, Mapping):
            return None, "llmfit cli top recommendation is invalid"
        profile = self._pick_profile(normalized)
        backend = str(profile.get("backend", "ollama")).strip() or "ollama"
        model = str(profile.get("model", "")).strip() or str(
            self._root.get("ollama", {}).get("model", "qwen2.5:1.5b")
        )
        fit_level = str(top.get("fit_level", "")).strip()
        fit_norm = fit_level.lower()
        if "perfect" in fit_norm:
            score = "perfect"
        elif "good" in fit_norm:
            score = "good"
        elif "marginal" in fit_norm:
            score = "marginal"
        else:
            score = str(profile.get("score", "good")).strip() or "good"
        candidate_name = str(top.get("name") or top.get("model") or "").strip()
        tps = top.get("estimated_tps", None)
        reason = f"llmfit_cli use_case={use_case or normalized}"
        if fit_level:
            reason += f" fit={fit_level}"
        if candidate_name:
            reason += f" top={candidate_name}"
        if isinstance(tps, (int, float)):
            reason += f" tps={round(float(tps), 1)}"
        _ = context
        return {
            "backend": backend,
            "model": model,
            "score": score,
            "reason": reason,
        }, None

    def _candidate_callables(self, module: Any) -> list[Callable[..., Any]]:
        candidates: list[Callable[..., Any]] = []
        recommend_fn = getattr(module, "recommend", None)
        if callable(recommend_fn):
            candidates.append(recommend_fn)

        engine_cls = getattr(module, "LLMFit", None)
        if engine_cls is not None:
            try:
                instance = engine_cls()
            except Exception:
                instance = None
            if instance is not None:
                method = getattr(instance, "recommend", None)
                if callable(method):
                    candidates.append(method)
        return candidates

    def _pick_profile(self, task_type: str) -> dict[str, Any]:
        normalized = _normalize_task_type(task_type)
        profile = _as_mapping(self._task_profiles.get(normalized))
        if profile:
            return profile
        profile = _as_mapping(DEFAULT_TASK_PROFILES.get(normalized))
        if profile:
            return profile
        return _as_mapping(DEFAULT_TASK_PROFILES["chat"])

    def _fallback(self, task_type: str, context: Mapping[str, Any] | None, reason: str) -> dict[str, Any]:
        normalized = _normalize_task_type(task_type)
        profile = self._pick_profile(normalized)
        model = str(profile.get("model", "")).strip() or str(
            self._root.get("ollama", {}).get("model", "qwen2.5:1.5b")
        )
        backend = str(profile.get("backend", "ollama")).strip() or "ollama"
        score = str(profile.get("score", "good")).strip() or "good"
        base_reason = str(profile.get("reason", "fallback profile")).strip()
        return {
            "task_type": normalized,
            "provider": self._provider,
            "backend": backend,
            "model": model,
            "score": score,
            "reason": f"{base_reason}; {reason}",
            "source": "fallback",
            "timeout_s": self._timeout_s,
            "ts": time.time(),
            "context": dict(context or {}),
        }

    def _normalize_external_result(
        self,
        result: Any,
        task_type: str,
        context: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        if isinstance(result, str):
            payload = {"model": result}
        elif isinstance(result, Mapping):
            payload = dict(result)
        else:
            raise ValueError(f"unsupported llmfit result type: {type(result).__name__}")

        normalized = _normalize_task_type(task_type)
        model = str(payload.get("model", "")).strip()
        backend = str(payload.get("backend", "ollama")).strip() or "ollama"
        score = str(payload.get("score", "good")).strip() or "good"
        reason = str(payload.get("reason", "llmfit recommendation")).strip()
        if not model:
            raise ValueError("llmfit result missing model")

        allowed = self._allowlists.get(normalized) or []
        if allowed and model not in allowed:
            return self._fallback(
                task_type=normalized,
                context=context,
                reason=f"model `{model}` rejected by allowlist",
            )

        return {
            "task_type": normalized,
            "provider": self._provider,
            "backend": backend,
            "model": model,
            "score": score,
            "reason": reason,
            "source": "llmfit",
            "timeout_s": self._timeout_s,
            "ts": time.time(),
            "context": dict(context or {}),
        }

    def get_best_model(self, task_type: str, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        normalized = _normalize_task_type(task_type)
        context_dict = dict(context or {})
        module, error = self._load_llmfit_module()
        python_reason: str | None = None
        if module is None:
            python_reason = error or "llmfit module unavailable"
            if error:
                self._logger.debug("llmfit unavailable: %s", error)
        else:
            callables = self._candidate_callables(module)
            if not callables:
                python_reason = "no compatible llmfit recommend callable found"
            for fn in callables:
                try:
                    result = _call_with_fallbacks(fn, normalized, context_dict)
                    return self._normalize_external_result(result, normalized, context_dict)
                except Exception as exc:
                    python_reason = f"llmfit callable `{getattr(fn, '__name__', 'callable')}` failed: {exc}"
                    self._logger.debug("llmfit callable failed (%s): %s", getattr(fn, "__name__", "callable"), exc)
                    continue

        cli_payload, cli_error = self._recommend_from_cli(normalized, context_dict)
        if cli_payload is not None:
            try:
                return self._normalize_external_result(cli_payload, normalized, context_dict)
            except Exception as exc:
                cli_error = f"llmfit cli normalize failed: {exc}"

        reasons = [reason for reason in (python_reason, cli_error) if reason]
        return self._fallback(
            task_type=normalized,
            context=context_dict,
            reason="; ".join(reasons) if reasons else "llmfit unavailable",
        )


_ROUTER_LOCK = threading.Lock()
_ROUTER_SINGLETON: HardwareAwareRouter | None = None


def get_hardware_router(
    config: Mapping[str, Any] | None = None,
    *,
    refresh: bool = False,
) -> HardwareAwareRouter:
    global _ROUTER_SINGLETON
    if refresh:
        with _ROUTER_LOCK:
            _ROUTER_SINGLETON = HardwareAwareRouter(config=config)
            return _ROUTER_SINGLETON
    if _ROUTER_SINGLETON is None:
        with _ROUTER_LOCK:
            if _ROUTER_SINGLETON is None:
                _ROUTER_SINGLETON = HardwareAwareRouter(config=config)
    return _ROUTER_SINGLETON


def get_best_model(
    task_type: str,
    context: Mapping[str, Any] | None = None,
    *,
    config: Mapping[str, Any] | None = None,
    refresh_router: bool = False,
) -> dict[str, Any]:
    """Public API required by step 1: resolve best model for a task."""
    router = get_hardware_router(config=config, refresh=refresh_router)
    return router.get_best_model(task_type=task_type, context=context)
