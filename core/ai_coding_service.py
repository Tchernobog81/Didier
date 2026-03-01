"""Coding generation service for AI routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable
from typing import Callable

import httpx

from core.config_schema import CodingConfig
from core.config_schema import OllamaConfig


class CodingServiceError(RuntimeError):
    """Raised when coding generation cannot proceed."""


@dataclass(frozen=True)
class CodingGenerationDeps:
    list_ollama_models: Callable[[str], Awaitable[list[str]]]
    pick_model: Callable[[list[str], list[str]], str | None]
    request_timeout: Callable[[], float]


async def generate_coding_response(
    *,
    prompt: str,
    ollama_config: OllamaConfig,
    coding_config: CodingConfig,
    deps: CodingGenerationDeps,
) -> dict[str, str]:
    base_url = str(ollama_config.base_url).strip().rstrip("/")
    coding_profile_model = ollama_config.coding_model or None
    configured_model = coding_config.model or ollama_config.model
    available_models = await deps.list_ollama_models(base_url)
    resolved_model = deps.pick_model(
        available_models,
        [configured_model, coding_profile_model, ollama_config.model or None],
    )
    if not resolved_model:
        raise CodingServiceError("Ollama unavailable: no model configured")

    num_predict = max(1, int(coding_config.num_predict))
    temperature = float(coding_config.temperature)
    system_prompt = str(coding_config.system_prompt or "").strip()
    full_prompt = prompt
    if system_prompt:
        full_prompt = f"{system_prompt}\n\nUser: {prompt}\nAssistant:"

    payload_data = {
        "model": resolved_model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": num_predict,
            "temperature": temperature,
        },
    }
    keep_alive = str(ollama_config.keep_alive or "").strip()
    if keep_alive:
        payload_data["keep_alive"] = keep_alive

    try:
        async with httpx.AsyncClient(timeout=deps.request_timeout()) as client:
            response = await client.post(f"{base_url}/api/generate", json=payload_data)
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise CodingServiceError(f"Ollama unavailable: {exc}")
    return {"response": str(data.get("response", "")).strip()}
