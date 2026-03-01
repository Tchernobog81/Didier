"""Concrete Didier config loading pipeline.

This module is intentionally additive and is not wired into the routers yet.
It defines the future canonical loading flow:

1. code defaults
2. config/config.json
3. explicit environment overrides
4. typed runtime config projection
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Mapping

from core.config import DidierConfig
from core.config_schema import ConfigValidationError
from core.config_schema import DidierRuntimeConfig
from core.config_schema import KNOWN_ROOT_SECTIONS
from core.config_schema import default_root_config

DEFAULT_CONFIG_PATH = Path(os.getenv("DIDIER_CONFIG_PATH", "config/config.json"))


def _parse_bool_env(raw: str) -> bool:
    text = str(raw).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigValidationError(f"Invalid boolean env override value: {raw}")


def _parse_int_env(raw: str) -> int:
    try:
        return int(str(raw).strip())
    except Exception as exc:
        raise ConfigValidationError(f"Invalid integer env override value: {raw}") from exc


def _parse_float_env(raw: str) -> float:
    try:
        return float(str(raw).strip())
    except Exception as exc:
        raise ConfigValidationError(f"Invalid float env override value: {raw}") from exc


def _parse_str_env(raw: str) -> str:
    return str(raw).strip()


@dataclass(frozen=True)
class EnvOverrideSpec:
    env_name: str
    dotted_path: str
    parser: Callable[[str], Any]


EXPLICIT_ENV_OVERRIDES: tuple[EnvOverrideSpec, ...] = (
    EnvOverrideSpec(
        "DIDIER_NPU_REQUIRED_FOR_VISION",
        "npu.required_for_vision",
        _parse_bool_env,
    ),
    EnvOverrideSpec("DIDIER_OLLAMA_BASE_URL", "ollama.base_url", _parse_str_env),
    EnvOverrideSpec("DIDIER_OLLAMA_MODEL", "ollama.model", _parse_str_env),
    EnvOverrideSpec("DIDIER_OLLAMA_ASK_MODEL", "ollama.model_profiles.ask", _parse_str_env),
    EnvOverrideSpec(
        "DIDIER_OLLAMA_CODING_MODEL",
        "ollama.model_profiles.coding",
        _parse_str_env,
    ),
    EnvOverrideSpec(
        "DIDIER_OLLAMA_ASK_AND_SPEAK_BUDGET_SECONDS",
        "ollama.ask_and_speak_budget_seconds",
        _parse_float_env,
    ),
    EnvOverrideSpec(
        "DIDIER_CHAT_RESPONSE_MAX_SENTENCES",
        "chat.response_max_sentences",
        _parse_int_env,
    ),
    EnvOverrideSpec(
        "DIDIER_CHAT_RESPONSE_MAX_CHARS",
        "chat.response_max_chars",
        _parse_int_env,
    ),
    EnvOverrideSpec(
        "DIDIER_TTS_RESPONSE_MAX_SENTENCES",
        "tts.response_max_sentences",
        _parse_int_env,
    ),
    EnvOverrideSpec(
        "DIDIER_TTS_RESPONSE_MAX_CHARS",
        "tts.response_max_chars",
        _parse_int_env,
    ),
    EnvOverrideSpec(
        "DIDIER_VISION_PRIMARY_FALLBACK_SECONDARY",
        "vision.primary_fallback_secondary",
        _parse_bool_env,
    ),
    EnvOverrideSpec(
        "DIDIER_VISION_API_LOCAL_CAPTURE_ENABLED",
        "vision.api_local_capture_enabled",
        _parse_bool_env,
    ),
)


@dataclass(frozen=True)
class LoadedConfig:
    path: Path
    raw: dict[str, Any]
    runtime: DidierRuntimeConfig
    fingerprint: str
    warnings: tuple[str, ...] = ()
    applied_overrides: tuple[str, ...] = ()

    def get(self, dotted_path: str, default: Any = None) -> Any:
        return self.runtime.get(dotted_path, default)

    def require(self, dotted_path: str) -> Any:
        return self.runtime.require(dotted_path)

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.raw)

    def to_legacy(self) -> DidierConfig:
        return DidierConfig.from_mapping(self.raw, source_path=self.path)


def _read_json_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigValidationError(f"Invalid JSON in config file: {path}") from exc
    if not isinstance(payload, dict):
        raise ConfigValidationError(f"Root config payload must be a mapping: {path}")
    return copy.deepcopy(payload)


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if (
            key in merged
            and isinstance(merged[key], dict)
            and isinstance(value, Mapping)
        ):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _set_dotted(target: dict[str, Any], dotted_path: str, value: Any) -> None:
    keys = [segment for segment in str(dotted_path or "").split(".") if segment]
    if not keys:
        raise ValueError("dotted_path required")
    node = target
    for key in keys[:-1]:
        child = node.get(key)
        if not isinstance(child, dict):
            child = {}
            node[key] = child
        node = child
    node[keys[-1]] = copy.deepcopy(value)


def _apply_env_overrides(
    payload: dict[str, Any],
    env: Mapping[str, str],
) -> tuple[dict[str, Any], tuple[str, ...]]:
    updated = copy.deepcopy(payload)
    applied: list[str] = []
    for spec in EXPLICIT_ENV_OVERRIDES:
        raw = env.get(spec.env_name)
        if raw is None or str(raw).strip() == "":
            continue
        parsed = spec.parser(str(raw))
        _set_dotted(updated, spec.dotted_path, parsed)
        applied.append(spec.env_name)
    return updated, tuple(applied)


def _collect_warnings(file_payload: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    unknown_roots = sorted(set(file_payload.keys()) - set(KNOWN_ROOT_SECTIONS))
    for key in unknown_roots:
        warnings.append(f"Unknown top-level config section: {key}")
    return warnings


def config_fingerprint(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha1(encoded).hexdigest()


def load_runtime_config(
    path: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> LoadedConfig:
    resolved = Path(path or DEFAULT_CONFIG_PATH)
    file_payload = _read_json_file(resolved)
    merged = _deep_merge(default_root_config(), file_payload)
    merged, applied_overrides = _apply_env_overrides(
        merged,
        env if env is not None else os.environ,
    )
    runtime = DidierRuntimeConfig.from_root(merged, source_path=resolved)
    return LoadedConfig(
        path=resolved,
        raw=merged,
        runtime=runtime,
        fingerprint=config_fingerprint(merged),
        warnings=tuple(_collect_warnings(file_payload)),
        applied_overrides=applied_overrides,
    )
