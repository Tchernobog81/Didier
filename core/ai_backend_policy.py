"""Pure backend policy helpers for AI routing."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any
from typing import Mapping
from urllib.parse import urlparse

from core.config_schema import OllamaConfig
from core.config_schema import PicobotConfig
from core.config_schema import RoutingConfig


def resolve_generate_timeout(
    ollama_config: OllamaConfig,
    routing_config: RoutingConfig,
    backend_choice: dict[str, Any] | None,
) -> float:
    timeout_s = max(2.0, min(float(ollama_config.timeout_seconds), 7.0))
    execution_backend = str((backend_choice or {}).get("execution_backend", "")).strip()
    if execution_backend == "pixel_ollama":
        pixel_timeout_s = min(
            timeout_s,
            float(routing_config.pixel_ollama_generate_timeout_s),
        )
        timeout_s = max(1.5, min(pixel_timeout_s, 6.0))
    return timeout_s


def resolve_local_fallback_timeout(
    routing_config: RoutingConfig,
    primary_timeout_s: float,
) -> float:
    configured = float(routing_config.local_ollama_fallback_timeout_s)
    if configured <= 0.0:
        fallback_timeout_s = max(1.8, min(float(primary_timeout_s) * 0.5, 2.8))
    else:
        fallback_timeout_s = configured
    return max(1.5, min(fallback_timeout_s, 3.0))


def resolve_gemini_boost_config(
    picobot_config: PicobotConfig,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env_map = env if env is not None else os.environ
    gemini = picobot_config.gemini
    api_key = (
        str(env_map.get("DIDIER_GEMINI_API_KEY", "")).strip()
        or str(gemini.api_key).strip()
    )
    payload = asdict(gemini)
    payload["api_key"] = api_key
    return payload


def is_local_didier_api_url(base_url: str) -> bool:
    parsed = urlparse(str(base_url or "").strip())
    if not (parsed.hostname or "").strip():
        return False
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return port in {5003, 5010}


def candidate_picobot_bases(
    picobot_config: PicobotConfig,
    *,
    fallback_bases: tuple[str, ...] = (),
) -> list[str]:
    candidates: list[str] = []
    if str(picobot_config.base_url).strip():
        candidates.append(str(picobot_config.base_url).strip().rstrip("/"))
    candidates.extend(str(item or "").strip().rstrip("/") for item in fallback_bases)

    deduped: list[str] = []
    seen: set[str] = set()
    for base in candidates:
        clean = str(base or "").strip().rstrip("/")
        if not clean:
            continue
        if is_local_didier_api_url(clean):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        deduped.append(clean)
    return deduped
