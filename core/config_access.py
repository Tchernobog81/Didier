"""Typed access helpers for Didier configuration.

This module provides a compatibility layer while the codebase still mixes:
- legacy DidierConfig
- raw mappings
- the new LoadedConfig wrapper
- the new DidierRuntimeConfig typed projection
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any
from typing import Mapping

from core.config import DidierConfig
from core.config_loader import LoadedConfig
from core.config_schema import ChatConfig
from core.config_schema import CodingConfig
from core.config_schema import DidierRuntimeConfig
from core.config_schema import NPUConfig
from core.config_schema import OllamaConfig
from core.config_schema import PicobotConfig
from core.config_schema import RoutingConfig
from core.config_schema import TTSConfig
from core.config_schema import VisionConfig

ConfigLike = DidierConfig | LoadedConfig | DidierRuntimeConfig | Mapping[str, Any]


def _copied_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): copy.deepcopy(value) for key, value in mapping.items()}


def effective_config_dict(config_like: ConfigLike) -> dict[str, Any]:
    if isinstance(config_like, LoadedConfig):
        return config_like.to_dict()
    if isinstance(config_like, DidierRuntimeConfig):
        return config_like.to_dict()
    if isinstance(config_like, DidierConfig):
        return config_like.to_dict()
    if isinstance(config_like, Mapping):
        return _copied_mapping(config_like)
    raise TypeError(f"Unsupported config object: {type(config_like)!r}")


def to_runtime_config(config_like: ConfigLike) -> DidierRuntimeConfig:
    if isinstance(config_like, LoadedConfig):
        return config_like.runtime
    if isinstance(config_like, DidierRuntimeConfig):
        return config_like
    if isinstance(config_like, DidierConfig):
        return DidierRuntimeConfig.from_root(
            config_like.to_dict(),
            source_path=config_like.source_path,
        )
    if isinstance(config_like, Mapping):
        return DidierRuntimeConfig.from_root(config_like)
    raise TypeError(f"Unsupported config object: {type(config_like)!r}")


def legacy_config(
    config_like: ConfigLike,
    *,
    source_path: str | Path = "<memory>",
) -> DidierConfig:
    if isinstance(config_like, DidierConfig):
        return config_like
    if isinstance(config_like, LoadedConfig):
        return config_like.to_legacy()
    if isinstance(config_like, DidierRuntimeConfig):
        return DidierConfig.from_mapping(
            config_like.to_dict(),
            source_path=config_like.source_path or source_path,
        )
    if isinstance(config_like, Mapping):
        return DidierConfig.from_mapping(
            effective_config_dict(config_like),
            source_path=source_path,
        )
    raise TypeError(f"Unsupported config object: {type(config_like)!r}")


def chat_settings(config_like: ConfigLike) -> ChatConfig:
    return to_runtime_config(config_like).chat


def npu_settings(config_like: ConfigLike) -> NPUConfig:
    return to_runtime_config(config_like).npu


def tts_settings(config_like: ConfigLike) -> TTSConfig:
    return to_runtime_config(config_like).tts


def coding_settings(config_like: ConfigLike) -> CodingConfig:
    return to_runtime_config(config_like).coding


def ollama_settings(config_like: ConfigLike) -> OllamaConfig:
    return to_runtime_config(config_like).ollama


def vision_settings(config_like: ConfigLike) -> VisionConfig:
    return to_runtime_config(config_like).vision


def picobot_settings(config_like: ConfigLike) -> PicobotConfig:
    return to_runtime_config(config_like).picobot


def routing_settings(config_like: ConfigLike) -> RoutingConfig:
    return to_runtime_config(config_like).routing
