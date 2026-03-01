"""Typed Didier configuration schema and validation helpers.

This module defines the future canonical defaults and typed access surface.
It is intentionally additive: existing routes are not migrated yet.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from dataclasses import field
from dataclasses import asdict
from pathlib import Path
from typing import Any
from typing import Mapping

KNOWN_ROOT_SECTIONS = frozenset(
    {
        "asr",
        "bluetooth",
        "chat",
        "coding",
        "hardware",
        "llmfit",
        "memory",
        "music",
        "npu",
        "ollama",
        "personality",
        "picobot",
        "routing",
        "storage",
        "tts",
        "vision",
    }
)


class ConfigValidationError(ValueError):
    """Raised when the config payload does not satisfy the schema."""


def _as_mapping(value: Any, *, context: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ConfigValidationError(f"{context} must be a mapping")
    return {str(key): copy.deepcopy(raw) for key, raw in value.items()}


def _coerce_str(value: Any, *, context: str, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _coerce_bool(value: Any, *, context: str, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    raise ConfigValidationError(f"{context} must be a boolean-like value")


def _coerce_int(
    value: Any,
    *,
    context: str,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if value is None:
        result = default
    else:
        try:
            result = int(value)
        except Exception as exc:
            raise ConfigValidationError(f"{context} must be an integer") from exc
    if minimum is not None and result < minimum:
        raise ConfigValidationError(f"{context} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ConfigValidationError(f"{context} must be <= {maximum}")
    return result


def _coerce_float(
    value: Any,
    *,
    context: str,
    default: float,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if value is None:
        result = default
    else:
        try:
            result = float(value)
        except Exception as exc:
            raise ConfigValidationError(f"{context} must be a float") from exc
    if minimum is not None and result < minimum:
        raise ConfigValidationError(f"{context} must be >= {minimum}")
    if maximum is not None and result > maximum:
        raise ConfigValidationError(f"{context} must be <= {maximum}")
    return result


def _nested_get(mapping: Mapping[str, Any], dotted_path: str, default: Any = None) -> Any:
    node: Any = mapping
    for key in str(dotted_path or "").split("."):
        if not isinstance(node, Mapping) or key not in node:
            return default
        node = node[key]
    return node


@dataclass(frozen=True)
class ChatConfig:
    response_max_sentences: int = 2
    response_max_chars: int = 150

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "ChatConfig":
        data = _as_mapping(mapping, context="chat")
        return cls(
            response_max_sentences=_coerce_int(
                data.get("response_max_sentences"),
                context="chat.response_max_sentences",
                default=2,
                minimum=1,
                maximum=4,
            ),
            response_max_chars=_coerce_int(
                data.get("response_max_chars"),
                context="chat.response_max_chars",
                default=150,
                minimum=40,
                maximum=500,
            ),
        )


@dataclass(frozen=True)
class TTSConfig:
    voice: str = "ff_siwis"
    lang: str = "fr-fr"
    output_path: str = "data/didier_speaks.wav"
    response_max_sentences: int = 1
    response_max_chars: int = 110

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "TTSConfig":
        data = _as_mapping(mapping, context="tts")
        return cls(
            voice=_coerce_str(data.get("voice"), context="tts.voice", default="ff_siwis"),
            lang=_coerce_str(data.get("lang"), context="tts.lang", default="fr-fr"),
            output_path=_coerce_str(
                data.get("output_path"),
                context="tts.output_path",
                default="data/didier_speaks.wav",
            ),
            response_max_sentences=_coerce_int(
                data.get("response_max_sentences"),
                context="tts.response_max_sentences",
                default=1,
                minimum=1,
                maximum=3,
            ),
            response_max_chars=_coerce_int(
                data.get("response_max_chars"),
                context="tts.response_max_chars",
                default=110,
                minimum=40,
                maximum=320,
            ),
        )


@dataclass(frozen=True)
class NPUConfig:
    device: str = "/dev/hailo0"
    pcie_address: str = "0001:01:00.0"
    required_for_vision: bool = False

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "NPUConfig":
        data = _as_mapping(mapping, context="npu")
        return cls(
            device=_coerce_str(
                data.get("device"),
                context="npu.device",
                default="/dev/hailo0",
            ),
            pcie_address=_coerce_str(
                data.get("pcie_address"),
                context="npu.pcie_address",
                default="0001:01:00.0",
            ),
            required_for_vision=_coerce_bool(
                data.get("required_for_vision"),
                context="npu.required_for_vision",
                default=False,
            ),
        )


@dataclass(frozen=True)
class CodingConfig:
    model: str = ""
    num_predict: int = 400
    temperature: float = 0.2
    system_prompt: str = ""

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "CodingConfig":
        data = _as_mapping(mapping, context="coding")
        return cls(
            model=_coerce_str(
                data.get("model"),
                context="coding.model",
                default="",
            ),
            num_predict=_coerce_int(
                data.get("num_predict"),
                context="coding.num_predict",
                default=400,
                minimum=1,
                maximum=4096,
            ),
            temperature=_coerce_float(
                data.get("temperature"),
                context="coding.temperature",
                default=0.2,
                minimum=0.0,
                maximum=2.0,
            ),
            system_prompt=_coerce_str(
                data.get("system_prompt"),
                context="coding.system_prompt",
                default="",
            ),
        )


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = "http://localhost:11434"
    model: str = "qwen2.5:1.5b"
    ask_model: str = "qwen2.5:1.5b"
    coding_model: str = "qwen2.5-coder:1.5b"
    timeout_seconds: float = 120.0
    num_predict: int = 48
    ask_num_predict: int = 36
    temperature: float = 0.4
    keep_alive: str = "10m"
    ask_and_speak_budget_seconds: float = 3.0
    model_profiles: dict[str, str] = field(
        default_factory=lambda: {
            "ask": "qwen2.5:1.5b",
            "coding": "qwen2.5-coder:1.5b",
        }
    )

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "OllamaConfig":
        data = _as_mapping(mapping, context="ollama")
        model_profiles = _as_mapping(data.get("model_profiles"), context="ollama.model_profiles")
        ask_model = _coerce_str(
            model_profiles.get("ask") or data.get("ask_model"),
            context="ollama.ask_model",
            default="qwen2.5:1.5b",
        )
        coding_model = _coerce_str(
            model_profiles.get("coding") or data.get("coding_model"),
            context="ollama.coding_model",
            default="qwen2.5-coder:1.5b",
        )
        normalized_profiles = {
            "ask": ask_model,
            "coding": coding_model,
        }
        return cls(
            base_url=_coerce_str(
                data.get("base_url"),
                context="ollama.base_url",
                default="http://localhost:11434",
            ),
            model=_coerce_str(
                data.get("model"),
                context="ollama.model",
                default="qwen2.5:1.5b",
            ),
            ask_model=ask_model,
            coding_model=coding_model,
            timeout_seconds=_coerce_float(
                data.get("timeout_seconds"),
                context="ollama.timeout_seconds",
                default=120.0,
                minimum=1.0,
                maximum=600.0,
            ),
            num_predict=_coerce_int(
                data.get("num_predict"),
                context="ollama.num_predict",
                default=48,
                minimum=1,
                maximum=4096,
            ),
            ask_num_predict=_coerce_int(
                data.get("ask_num_predict"),
                context="ollama.ask_num_predict",
                default=36,
                minimum=1,
                maximum=1024,
            ),
            temperature=_coerce_float(
                data.get("temperature"),
                context="ollama.temperature",
                default=0.4,
                minimum=0.0,
                maximum=2.0,
            ),
            keep_alive=_coerce_str(
                data.get("keep_alive"),
                context="ollama.keep_alive",
                default="10m",
            ),
            ask_and_speak_budget_seconds=_coerce_float(
                data.get("ask_and_speak_budget_seconds"),
                context="ollama.ask_and_speak_budget_seconds",
                default=3.0,
                minimum=0.5,
                maximum=30.0,
            ),
            model_profiles=normalized_profiles,
        )


@dataclass(frozen=True)
class VisionConfig:
    camera_index: int = 0
    camera_device: str = "/dev/video0"
    width: int = 640
    height: int = 480
    fps: int = 15
    fourcc: str = "YUYV"
    enable_live: bool = True
    api_local_capture_enabled: bool = True
    primary_fallback_secondary: bool = True
    kill_on_open: bool = False
    remote_stream_enabled: bool = True
    remote_stream_input_url: str = "udp://0.0.0.0:1234"
    remote_stream_fps: int = 15

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "VisionConfig":
        data = _as_mapping(mapping, context="vision")
        remote_stream = _as_mapping(data.get("remote_stream"), context="vision.remote_stream")
        return cls(
            camera_index=_coerce_int(
                data.get("camera_index"),
                context="vision.camera_index",
                default=0,
                minimum=0,
                maximum=16,
            ),
            camera_device=_coerce_str(
                data.get("camera_device"),
                context="vision.camera_device",
                default="/dev/video0",
            ),
            width=_coerce_int(
                data.get("width"),
                context="vision.width",
                default=640,
                minimum=1,
                maximum=4096,
            ),
            height=_coerce_int(
                data.get("height"),
                context="vision.height",
                default=480,
                minimum=1,
                maximum=4096,
            ),
            fps=_coerce_int(
                data.get("fps"),
                context="vision.fps",
                default=15,
                minimum=1,
                maximum=120,
            ),
            fourcc=_coerce_str(
                data.get("fourcc"),
                context="vision.fourcc",
                default="YUYV",
            ),
            enable_live=_coerce_bool(
                data.get("enable_live"),
                context="vision.enable_live",
                default=True,
            ),
            api_local_capture_enabled=_coerce_bool(
                data.get("api_local_capture_enabled"),
                context="vision.api_local_capture_enabled",
                default=True,
            ),
            primary_fallback_secondary=_coerce_bool(
                data.get("primary_fallback_secondary"),
                context="vision.primary_fallback_secondary",
                default=True,
            ),
            kill_on_open=_coerce_bool(
                data.get("kill_on_open"),
                context="vision.kill_on_open",
                default=False,
            ),
            remote_stream_enabled=_coerce_bool(
                remote_stream.get("enabled"),
                context="vision.remote_stream.enabled",
                default=True,
            ),
            remote_stream_input_url=_coerce_str(
                remote_stream.get("input_url"),
                context="vision.remote_stream.input_url",
                default="udp://0.0.0.0:1234",
            ),
            remote_stream_fps=_coerce_int(
                remote_stream.get("fps"),
                context="vision.remote_stream.fps",
                default=15,
                minimum=1,
                maximum=120,
            ),
        )


@dataclass(frozen=True)
class PicobotGeminiConfig:
    enabled: bool = False
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    model: str = "gemini-1.5-flash"
    api_key: str = ""
    timeout_s: float = 3.2
    max_tokens: int = 220
    memory_enabled: bool = True
    memory_items: int = 6
    memory_path: str = "data/gemini_boost_memory.jsonl"
    memory_max_bytes: int = 262144

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "PicobotGeminiConfig":
        data = _as_mapping(mapping, context="picobot.gemini")
        return cls(
            enabled=_coerce_bool(
                data.get("enabled"),
                context="picobot.gemini.enabled",
                default=False,
            ),
            base_url=_coerce_str(
                data.get("base_url"),
                context="picobot.gemini.base_url",
                default="https://generativelanguage.googleapis.com/v1beta",
            ),
            model=_coerce_str(
                data.get("model"),
                context="picobot.gemini.model",
                default="gemini-1.5-flash",
            ),
            api_key=_coerce_str(
                data.get("api_key"),
                context="picobot.gemini.api_key",
                default="",
            ),
            timeout_s=_coerce_float(
                data.get("timeout_s"),
                context="picobot.gemini.timeout_s",
                default=3.2,
                minimum=0.4,
                maximum=12.0,
            ),
            max_tokens=_coerce_int(
                data.get("max_tokens"),
                context="picobot.gemini.max_tokens",
                default=220,
                minimum=64,
                maximum=384,
            ),
            memory_enabled=_coerce_bool(
                data.get("memory_enabled"),
                context="picobot.gemini.memory_enabled",
                default=True,
            ),
            memory_items=_coerce_int(
                data.get("memory_items"),
                context="picobot.gemini.memory_items",
                default=6,
                minimum=0,
                maximum=20,
            ),
            memory_path=_coerce_str(
                data.get("memory_path"),
                context="picobot.gemini.memory_path",
                default="data/gemini_boost_memory.jsonl",
            ),
            memory_max_bytes=_coerce_int(
                data.get("memory_max_bytes"),
                context="picobot.gemini.memory_max_bytes",
                default=262144,
                minimum=16384,
                maximum=2 * 1024 * 1024,
            ),
        )


@dataclass(frozen=True)
class PicobotConfig:
    base_url: str = ""
    llm_endpoint: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
    react_timeout_s: float = 5.0
    brain_fallback_enabled: bool = False
    anomaly_react_enabled: bool = True
    react_filter_default: bool = False
    gemini: PicobotGeminiConfig = field(default_factory=PicobotGeminiConfig)

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "PicobotConfig":
        data = _as_mapping(mapping, context="picobot")
        base_url = ""
        for key in (
            "base_url",
            "url",
            "agent_url",
            "service_url",
            "worker_url",
            "runtime_url",
            "api_url",
        ):
            candidate = _coerce_str(
                data.get(key),
                context=f"picobot.{key}",
                default="",
            )
            if candidate:
                base_url = candidate.rstrip("/")
                break
        return cls(
            base_url=base_url,
            llm_endpoint=_coerce_str(
                data.get("llm_endpoint"),
                context="picobot.llm_endpoint",
                default="",
            ).rstrip("/"),
            llm_model=_coerce_str(
                data.get("llm_model"),
                context="picobot.llm_model",
                default="",
            ),
            llm_api_key=_coerce_str(
                data.get("llm_api_key"),
                context="picobot.llm_api_key",
                default="",
            ),
            react_timeout_s=_coerce_float(
                data.get("react_timeout_s"),
                context="picobot.react_timeout_s",
                default=5.0,
                minimum=0.5,
                maximum=15.0,
            ),
            brain_fallback_enabled=_coerce_bool(
                data.get("brain_fallback_enabled"),
                context="picobot.brain_fallback_enabled",
                default=False,
            ),
            anomaly_react_enabled=_coerce_bool(
                data.get("anomaly_react_enabled"),
                context="picobot.anomaly_react_enabled",
                default=True,
            ),
            react_filter_default=_coerce_bool(
                data.get("react_filter_default"),
                context="picobot.react_filter_default",
                default=False,
            ),
            gemini=PicobotGeminiConfig.from_mapping(data.get("gemini")),
        )


@dataclass(frozen=True)
class RoutingConfig:
    pixel_ollama_health_timeout_s: float = 2.0
    pixel_ollama_generate_timeout_s: float = 5.5
    local_ollama_fallback_timeout_s: float = 0.0
    pixel_openai_max_tokens: int = 128

    @classmethod
    def from_mapping(cls, mapping: Mapping[str, Any] | None) -> "RoutingConfig":
        data = _as_mapping(mapping, context="routing")
        pixel_ollama = _as_mapping(data.get("pixel_ollama"), context="routing.pixel_ollama")
        local_ollama = _as_mapping(data.get("local_ollama"), context="routing.local_ollama")
        pixel_openai = _as_mapping(data.get("pixel_openai"), context="routing.pixel_openai")
        return cls(
            pixel_ollama_health_timeout_s=_coerce_float(
                pixel_ollama.get("health_timeout_s"),
                context="routing.pixel_ollama.health_timeout_s",
                default=2.0,
                minimum=0.1,
                maximum=10.0,
            ),
            pixel_ollama_generate_timeout_s=_coerce_float(
                pixel_ollama.get("generate_timeout_s"),
                context="routing.pixel_ollama.generate_timeout_s",
                default=5.5,
                minimum=0.5,
                maximum=10.0,
            ),
            local_ollama_fallback_timeout_s=_coerce_float(
                local_ollama.get("fallback_timeout_s"),
                context="routing.local_ollama.fallback_timeout_s",
                default=0.0,
                minimum=0.0,
                maximum=10.0,
            ),
            pixel_openai_max_tokens=_coerce_int(
                pixel_openai.get("max_tokens"),
                context="routing.pixel_openai.max_tokens",
                default=128,
                minimum=32,
                maximum=2048,
            ),
        )


@dataclass(frozen=True)
class DidierRuntimeConfig:
    root: dict[str, Any]
    npu: NPUConfig
    chat: ChatConfig
    tts: TTSConfig
    coding: CodingConfig
    ollama: OllamaConfig
    vision: VisionConfig
    picobot: PicobotConfig
    routing: RoutingConfig
    source_path: Path | None = None

    @classmethod
    def from_root(
        cls,
        root: Mapping[str, Any],
        *,
        source_path: str | Path | None = None,
    ) -> "DidierRuntimeConfig":
        payload = _as_mapping(root, context="root")
        return cls(
            root=payload,
            npu=NPUConfig.from_mapping(payload.get("npu")),
            chat=ChatConfig.from_mapping(payload.get("chat")),
            tts=TTSConfig.from_mapping(payload.get("tts")),
            coding=CodingConfig.from_mapping(payload.get("coding")),
            ollama=OllamaConfig.from_mapping(payload.get("ollama")),
            vision=VisionConfig.from_mapping(payload.get("vision")),
            picobot=PicobotConfig.from_mapping(payload.get("picobot")),
            routing=RoutingConfig.from_mapping(payload.get("routing")),
            source_path=Path(source_path) if source_path is not None else None,
        )

    def get(self, dotted_path: str, default: Any = None) -> Any:
        return _nested_get(self.root, dotted_path, default)

    def require(self, dotted_path: str) -> Any:
        value = self.get(dotted_path, default=None)
        if value is None:
            raise KeyError(f"Missing required config key: {dotted_path}")
        return value

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.root)


def default_root_config() -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "npu": asdict(NPUConfig()),
        "chat": asdict(ChatConfig()),
        "tts": asdict(TTSConfig()),
        "coding": asdict(CodingConfig()),
        "ollama": {
            "base_url": OllamaConfig().base_url,
            "model": OllamaConfig().model,
            "model_profiles": copy.deepcopy(OllamaConfig().model_profiles),
            "timeout_seconds": OllamaConfig().timeout_seconds,
            "num_predict": OllamaConfig().num_predict,
            "ask_num_predict": OllamaConfig().ask_num_predict,
            "temperature": OllamaConfig().temperature,
            "keep_alive": OllamaConfig().keep_alive,
            "ask_and_speak_budget_seconds": OllamaConfig().ask_and_speak_budget_seconds,
        },
        "vision": {
            "camera_index": VisionConfig().camera_index,
            "camera_device": VisionConfig().camera_device,
            "width": VisionConfig().width,
            "height": VisionConfig().height,
            "fps": VisionConfig().fps,
            "fourcc": VisionConfig().fourcc,
            "enable_live": VisionConfig().enable_live,
            "api_local_capture_enabled": VisionConfig().api_local_capture_enabled,
            "primary_fallback_secondary": VisionConfig().primary_fallback_secondary,
            "kill_on_open": VisionConfig().kill_on_open,
            "remote_stream": {
                "enabled": VisionConfig().remote_stream_enabled,
                "input_url": VisionConfig().remote_stream_input_url,
                "fps": VisionConfig().remote_stream_fps,
            },
        },
        "picobot": {
            "base_url": PicobotConfig().base_url,
            "llm_endpoint": PicobotConfig().llm_endpoint,
            "llm_model": PicobotConfig().llm_model,
            "llm_api_key": PicobotConfig().llm_api_key,
            "react_timeout_s": PicobotConfig().react_timeout_s,
            "brain_fallback_enabled": PicobotConfig().brain_fallback_enabled,
            "anomaly_react_enabled": PicobotConfig().anomaly_react_enabled,
            "react_filter_default": PicobotConfig().react_filter_default,
            "gemini": asdict(PicobotGeminiConfig()),
        },
        "routing": {
            "pixel_ollama": {
                "health_timeout_s": RoutingConfig().pixel_ollama_health_timeout_s,
                "generate_timeout_s": RoutingConfig().pixel_ollama_generate_timeout_s,
            },
            "local_ollama": {
                "fallback_timeout_s": RoutingConfig().local_ollama_fallback_timeout_s,
            },
            "pixel_openai": {
                "max_tokens": RoutingConfig().pixel_openai_max_tokens,
            },
        },
    }
    return defaults
