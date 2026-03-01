"""Conversation generation service for AI routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable

import httpx

from core.ai_backend_policy import resolve_generate_timeout
from core.ai_backend_policy import resolve_local_fallback_timeout
from core.config_schema import OllamaConfig
from core.config_schema import PicobotConfig
from core.config_schema import RoutingConfig


class ConversationServiceError(RuntimeError):
    """Raised when conversation generation cannot proceed."""


@dataclass(frozen=True)
class ConversationGenerationDeps:
    runtime_qos_snapshot: Callable[[], dict[str, Any]]
    flag_enabled: Callable[[object], bool]
    try_gemini_boost_chat: Callable[..., Awaitable[tuple[str | None, str | None]]]
    try_pixel_openai_chat: Callable[..., Awaitable[tuple[str | None, str | None]]]
    resolve_ollama_base_for_backend: Callable[..., Awaitable[tuple[str, dict[str, Any], list[str]]]]
    list_ollama_models: Callable[[str], Awaitable[list[str]]]
    pick_model: Callable[[list[str], list[str]], str | None]
    finalize_model_response: Callable[[str], str]
    is_listening_only_response: Callable[[str], bool]
    llm_http_timeout: Callable[[float | int], float]
    http_error_brief: Callable[[Exception], str]
    resolve_gemini_boost_config: Callable[[PicobotConfig], dict[str, Any]]


async def generate_conversation_response(
    *,
    clean_prompt: str,
    task_type: str,
    expert_model: str | None,
    expert_system: str | None,
    backend_choice: dict[str, Any],
    payload: dict[str, Any],
    orchestrator: Any,
    api_module: Any,
    ollama_config: OllamaConfig,
    picobot_config: PicobotConfig,
    routing_config: RoutingConfig,
    deps: ConversationGenerationDeps,
) -> dict[str, Any]:
    qos = deps.runtime_qos_snapshot()
    mode = str(qos.get("mode", "NOMINAL")).upper()
    llm_profile = str(qos.get("llm_profile", "full")).lower()
    try:
        budget_hint_s = float((payload or {}).get("llm_budget_s", 0.0) or 0.0)
    except Exception:
        budget_hint_s = 0.0
    if budget_hint_s < 0.0:
        budget_hint_s = 0.0
    compact_mode = mode == "SURVIE" or llm_profile == "compact"
    ask_profile_model = ollama_config.ask_model or None
    default_model = ollama_config.model or None
    ask_num_predict = int(ollama_config.ask_num_predict or ollama_config.num_predict or 36)
    if ask_num_predict <= 0:
        ask_num_predict = 36
    ask_num_predict = max(16, min(ask_num_predict, 96))
    if compact_mode:
        ask_num_predict = min(ask_num_predict, 24)
    elif mode == "TENDU":
        ask_num_predict = min(ask_num_predict, 32)
    else:
        ask_num_predict = min(ask_num_predict, 48)
    execution_backend = str(backend_choice.get("execution_backend", "")).strip()
    preferred_backend = str(backend_choice.get("preferred_backend", "")).strip()
    boost_requested = deps.flag_enabled((payload or {}).get("boost", False))
    gemini_cfg = deps.resolve_gemini_boost_config(picobot_config)
    if boost_requested:
        backend_choice["boost_requested"] = True
        if mode == "SURVIE":
            backend_choice["boost_active"] = False
            backend_choice["boost_error"] = "survie_mode"
            backend_choice["fallback_active"] = True
            backend_choice["fallback_reason"] = "gemini_boost_skipped_survie_mode"
        else:
            gemini_timeout_s = min(
                float(gemini_cfg.get("timeout_s", 3.2) or 3.2),
                3.4 if mode == "NOMINAL" else 2.8,
            )
            if budget_hint_s > 0.0:
                gemini_timeout_s = min(gemini_timeout_s, max(0.45, budget_hint_s - 0.5))
            gemini_max_tokens = int(gemini_cfg.get("max_tokens", 220) or 220)
            gemini_text, gemini_error = await deps.try_gemini_boost_chat(
                orchestrator=orchestrator,
                prompt=clean_prompt,
                system_prompt=expert_system,
                max_tokens=max(64, min(gemini_max_tokens, 320)),
                timeout_s=gemini_timeout_s,
            )
            if gemini_text:
                response = deps.finalize_model_response(str(gemini_text).strip())
                if not response:
                    response = "Je t'ecoute."
                if deps.is_listening_only_response(response):
                    response = "Salut. Dis-moi l'action precise que tu veux lancer."
                backend_choice["execution_backend"] = "gemini_boost"
                backend_choice["boost_active"] = True
                backend_choice["fallback_active"] = False
                backend_choice["boost_error"] = ""
                api_module.update_status(
                    thinking=False,
                    state="IDLE",
                    last_response=response,
                    last_response_at=api_module.time.time(),
                )
                return {
                    "response": response,
                    "model": str(gemini_cfg.get("model", "")).strip() or "gemini",
                    "task": False,
                    "route": "gemini_boost",
                    "task_type": task_type,
                    "routing": backend_choice,
                }
            backend_choice["boost_active"] = False
            backend_choice["boost_error"] = gemini_error or "unknown"
            backend_choice["fallback_active"] = True
            backend_choice["fallback_reason"] = f"gemini_boost_failed:{gemini_error or 'unknown'}"
    should_try_pixel_openai = execution_backend == "pixel_ollama" or preferred_backend == "pixel_tpu"
    if mode == "TENDU" and should_try_pixel_openai:
        backend_choice["execution_backend"] = "local_ollama"
        backend_choice["fallback_active"] = True
        backend_choice["fallback_reason"] = "arbitration_tendu_local_only"
        should_try_pixel_openai = False
    if compact_mode and should_try_pixel_openai:
        backend_choice["execution_backend"] = "local_ollama"
        backend_choice["fallback_active"] = True
        backend_choice["fallback_reason"] = "arbitration_compact_mode"
        should_try_pixel_openai = False
    backend_choice["arbitration_mode"] = mode
    backend_choice["llm_profile"] = llm_profile
    if should_try_pixel_openai:
        pixel_timeout_s = resolve_generate_timeout(
            ollama_config,
            routing_config,
            backend_choice,
        )
        if compact_mode:
            pixel_timeout_s = min(pixel_timeout_s, 2.4)
        elif mode == "TENDU":
            pixel_timeout_s = min(pixel_timeout_s, 3.0)
        else:
            pixel_timeout_s = min(pixel_timeout_s, 3.4)
        if budget_hint_s > 0.0:
            pixel_timeout_s = min(pixel_timeout_s, max(0.45, budget_hint_s - 0.5))
        pixel_max_tokens = int(routing_config.pixel_openai_max_tokens)
        pixel_text, pixel_error = await deps.try_pixel_openai_chat(
            orchestrator=orchestrator,
            prompt=clean_prompt,
            system_prompt=expert_system,
            max_tokens=max(64, min(pixel_max_tokens, 220)),
            timeout_s=pixel_timeout_s,
        )
        if pixel_text:
            response = deps.finalize_model_response(str(pixel_text).strip())
            if deps.is_listening_only_response(response):
                response = "Salut. Dis-moi l'action precise que tu veux lancer."
            backend_choice["execution_backend"] = "pixel_openai"
            api_module.update_status(
                thinking=False,
                state="IDLE",
                last_response=response,
                last_response_at=api_module.time.time(),
            )
            return {
                "response": response,
                "model": str(picobot_config.llm_model).strip() or "pixel_openai",
                "task": False,
                "route": "pixel_openai",
                "task_type": task_type,
                "routing": backend_choice,
            }
        backend_choice["execution_backend"] = "local_ollama"
        backend_choice["fallback_active"] = True
        backend_choice["fallback_reason"] = f"pixel_openai_failed:{pixel_error or 'unknown'}"

    base_url, backend_choice, preloaded_models = await deps.resolve_ollama_base_for_backend(
        orchestrator=orchestrator,
        backend_choice=backend_choice,
        payload=payload,
    )
    skip_model_discovery = compact_mode or mode == "TENDU"
    if preloaded_models:
        available_models = preloaded_models
    elif skip_model_discovery:
        available_models = []
    else:
        available_models = await deps.list_ollama_models(base_url)
    resolved_model = deps.pick_model(
        available_models,
        [
            expert_model,
            str(backend_choice.get("recommended_model", "")).strip(),
            ask_profile_model,
            default_model,
        ],
    )
    if not resolved_model:
        raise ConversationServiceError("Ollama unavailable: no model configured")

    if compact_mode:
        full_prompt = f"Reponds en francais en une phrase courte et concrete.\n{clean_prompt}"
    else:
        full_prompt = f"Reponds en francais en 1 a 2 phrases courtes et concretes.\n{clean_prompt}"
    if expert_system:
        prompt_prefix = (
            "Reponds en francais en une phrase courte et concrete."
            if compact_mode
            else "Reponds en francais en 1 a 2 phrases courtes et concretes."
        )
        full_prompt = f"{prompt_prefix}\n{str(expert_system).strip()}\n\n{clean_prompt}"
    payload_data: dict[str, Any] = {
        "model": resolved_model,
        "prompt": full_prompt,
        "stream": False,
        "options": {
            "num_predict": ask_num_predict,
            "temperature": float(ollama_config.temperature),
        },
    }
    keep_alive = ollama_config.keep_alive
    if keep_alive:
        payload_data["keep_alive"] = keep_alive

    timeout_s = resolve_generate_timeout(
        ollama_config,
        routing_config,
        backend_choice,
    )
    fallback_timeout_s = resolve_local_fallback_timeout(
        routing_config,
        timeout_s,
    )
    if compact_mode:
        timeout_s = min(timeout_s, 3.2)
        fallback_timeout_s = min(fallback_timeout_s, 1.6)
    elif mode == "TENDU":
        timeout_s = min(timeout_s, 2.6)
        fallback_timeout_s = min(fallback_timeout_s, 1.4)
    else:
        timeout_s = min(timeout_s, 4.2)
        fallback_timeout_s = min(fallback_timeout_s, 2.2)
    if budget_hint_s > 0.0:
        timeout_s = min(timeout_s, max(0.45, budget_hint_s - 0.5))
        fallback_timeout_s = min(fallback_timeout_s, max(0.35, budget_hint_s * 0.45))
    url = f"{base_url}/api/generate"
    try:
        api_module.update_status(
            thinking=True,
            state="THINKING",
            last_prompt=clean_prompt,
            last_prompt_at=api_module.time.time(),
        )
        async with httpx.AsyncClient(timeout=deps.llm_http_timeout(timeout_s)) as client:
            ollama_response = await client.post(url, json=payload_data)
            ollama_response.raise_for_status()
            data = ollama_response.json()
        response = deps.finalize_model_response(str(data.get("response", "")).strip())
        if not response:
            response = "Je t'ecoute."
        if deps.is_listening_only_response(response):
            response = "Salut. Dis-moi l'action precise que tu veux lancer."
        api_module.update_status(
            thinking=False,
            state="IDLE",
            last_response=response,
            last_response_at=api_module.time.time(),
        )
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        local_base_url = str(ollama_config.base_url).strip().rstrip("/")
        can_retry_local = (
            str(backend_choice.get("execution_backend", "")).strip() == "pixel_ollama"
            and base_url != local_base_url
        )
        if can_retry_local:
            fallback_url = f"{local_base_url}/api/generate"
            try:
                async with httpx.AsyncClient(timeout=deps.llm_http_timeout(fallback_timeout_s)) as client:
                    fallback_response = await client.post(fallback_url, json=payload_data)
                    fallback_response.raise_for_status()
                    fallback_data = fallback_response.json()
                response = deps.finalize_model_response(str(fallback_data.get("response", "")).strip())
                if not response:
                    response = "Je t'ecoute."
                if deps.is_listening_only_response(response):
                    response = "Salut. Dis-moi l'action precise que tu veux lancer."
                backend_choice["execution_backend"] = "local_ollama"
                backend_choice["fallback_active"] = True
                backend_choice["fallback_reason"] = f"pixel_generate_failed:{deps.http_error_brief(exc)}"
                api_module.update_status(
                    thinking=False,
                    state="IDLE",
                    last_response=response,
                    last_response_at=api_module.time.time(),
                )
                return {
                    "response": response,
                    "model": resolved_model,
                    "task": False,
                    "route": "ollama",
                    "task_type": task_type,
                    "routing": backend_choice,
                }
            except asyncio.CancelledError:
                raise
            except Exception:
                pass
        backend_choice["fallback_active"] = True
        backend_choice["fallback_reason"] = (
            backend_choice.get("fallback_reason")
            or f"ollama_generate_failed:{deps.http_error_brief(exc)}"
        )
        api_module.update_status(
            thinking=False,
            state="IDLE",
            error=f"{deps.http_error_brief(exc)}",
        )
        return {
            "response": "Je suis encore en charge. Reessaie dans quelques secondes.",
            "model": resolved_model,
            "task": False,
            "route": "stub",
            "task_type": task_type,
            "routing": backend_choice,
        }
    return {
        "response": response,
        "model": resolved_model,
        "task": False,
        "route": "ollama",
        "task_type": task_type,
        "routing": backend_choice,
    }
