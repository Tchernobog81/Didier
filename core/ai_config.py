"""Pure helpers for AI route configuration access and text compaction."""

from __future__ import annotations

import re
from typing import Any

from core.config_access import chat_settings
from core.config_access import coding_settings
from core.config_access import ollama_settings
from core.config_access import picobot_settings
from core.config_access import routing_settings
from core.config_access import tts_settings
from core.text_compaction import compact_text


def config_subject(orchestrator: Any) -> Any:
    if orchestrator is None:
        return {}
    loaded = getattr(orchestrator, "loaded_config", None)
    if loaded is not None:
        return loaded
    runtime = getattr(orchestrator, "runtime_config", None)
    if runtime is not None:
        return runtime
    return getattr(orchestrator, "config", {})


def chat_cfg(orchestrator: Any):
    return chat_settings(config_subject(orchestrator))


def tts_cfg(orchestrator: Any):
    return tts_settings(config_subject(orchestrator))


def coding_cfg(orchestrator: Any):
    return coding_settings(config_subject(orchestrator))


def ollama_cfg(orchestrator: Any):
    return ollama_settings(config_subject(orchestrator))


def picobot_cfg(orchestrator: Any):
    return picobot_settings(config_subject(orchestrator))


def routing_cfg(orchestrator: Any):
    return routing_settings(config_subject(orchestrator))


def prepare_tts_text(
    text: str,
    orchestrator: Any,
    *,
    qos: dict[str, Any] | None = None,
) -> str:
    spoken = str(text or "").strip()
    if not spoken:
        return ""
    spoken = re.sub(r"https?://\S+", "", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\bsource\s*:\s*[^.]+\.?", "", spoken, flags=re.IGNORECASE)
    spoken = re.sub(r"\s+", " ", spoken).strip()
    tts_config = tts_cfg(orchestrator)
    max_sentences = max(1, min(int(tts_config.response_max_sentences), 3))
    max_chars = max(40, min(int(tts_config.response_max_chars), 320))
    qos_data = qos if isinstance(qos, dict) else {}
    mode = str(qos_data.get("mode", "NOMINAL")).upper()
    llm_profile = str(qos_data.get("llm_profile", "full")).lower()
    try:
        queue_size = int(qos_data.get("audio_queue_size", 0) or 0)
    except Exception:
        queue_size = 0
    speaking = bool(qos_data.get("audio_speaking", False))
    if mode == "SURVIE" or llm_profile == "compact":
        max_sentences = 1
        max_chars = min(max_chars, 95)
    elif mode == "TENDU":
        max_sentences = min(max_sentences, 2)
        max_chars = min(max_chars, 130)
    if queue_size > 0 or speaking:
        max_sentences = 1
        max_chars = min(max_chars, 105)
    return compact_text(
        spoken,
        max_sentences=max_sentences,
        max_chars=max_chars,
    )


def prepare_chat_text(
    text: str,
    orchestrator: Any,
    *,
    qos: dict[str, Any] | None = None,
) -> str:
    chat = str(text or "").strip()
    if not chat:
        return ""
    chat_config = chat_cfg(orchestrator)
    max_sentences = max(1, min(int(chat_config.response_max_sentences), 4))
    max_chars = max(50, min(int(chat_config.response_max_chars), 360))
    qos_data = qos if isinstance(qos, dict) else {}
    mode = str(qos_data.get("mode", "NOMINAL")).upper()
    llm_profile = str(qos_data.get("llm_profile", "full")).lower()
    if mode == "SURVIE" or llm_profile == "compact":
        max_sentences = 1
        max_chars = min(max_chars, 95)
    elif mode == "TENDU":
        max_sentences = min(max_sentences, 2)
        max_chars = min(max_chars, 125)
    else:
        max_sentences = min(max_sentences, 2)
        max_chars = min(max_chars, 170)
    return compact_text(
        chat,
        max_sentences=max_sentences,
        max_chars=max_chars,
    )
