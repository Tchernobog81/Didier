"""Ask-and-speak orchestration service for AI routes."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable

from core.config_schema import OllamaConfig


@dataclass(frozen=True)
class AskAndSpeakDeps:
    looks_like_web_query: Callable[[str], bool]
    looks_like_task_request: Callable[..., bool]
    process_input: Callable[..., Awaitable[dict[str, Any]]]
    prepare_chat_text: Callable[..., str]
    runtime_qos_snapshot: Callable[[], dict[str, Any]]
    resolve_expert_prompt: Callable[[str, object], tuple[str, str | None, str | None, Any]]
    infer_task_type: Callable[..., str]
    choose_backend: Callable[[str, str, dict[str, Any]], dict[str, Any]]
    normalize_text: Callable[[str], str]
    looks_like_identity_query: Callable[[str], bool]
    looks_like_local_status_query: Callable[[str], bool]
    deliver_dual_response: Callable[..., Awaitable[dict[str, Any]]]
    parse_switch_action: Callable[[str], str | None]
    resolve_actuator_target: Callable[..., tuple[str, str] | None]
    is_music_prompt: Callable[[str], bool]
    generate_conversation_response: Callable[..., Awaitable[dict[str, Any]]]


async def _with_delivery(
    *,
    result: dict[str, Any],
    response: str,
    orchestrator: Any,
    api_module: Any,
    is_voice_request: bool,
    deps: AskAndSpeakDeps,
) -> dict[str, Any]:
    payload = dict(result)
    payload.update(
        await deps.deliver_dual_response(
            response,
            orchestrator=orchestrator,
            api_module=api_module,
            is_voice_request=is_voice_request,
        )
    )
    return payload


def _is_task_request(prompt: str, payload: dict[str, Any], deps: AskAndSpeakDeps) -> tuple[bool, bool, bool]:
    force_task = bool(payload.get("force_task", False))
    is_voice_request = bool(payload.get("is_voice", False))
    is_web_request = deps.looks_like_web_query(prompt)
    task_candidate = deps.looks_like_task_request(
        prompt,
        is_voice=is_voice_request,
    )
    if not is_voice_request and not force_task:
        task_candidate = False
    return force_task or task_candidate or is_web_request, is_voice_request, is_web_request


def _routed_task_payload(
    payload: dict[str, Any],
    *,
    is_task_request: bool,
    is_web_request: bool,
) -> dict[str, Any]:
    routed_payload = dict(payload)
    if is_task_request:
        min_timeout_s = 6.5 if is_web_request else 5.8
        try:
            current_timeout_s = float(routed_payload.get("react_timeout_s", 0.0) or 0.0)
        except Exception:
            current_timeout_s = 0.0
        routed_payload["react_timeout_s"] = max(current_timeout_s, min_timeout_s)
    if is_web_request:
        routed_payload["web_query"] = True
    return routed_payload


def _language_ack_requested(prompt_norm: str) -> bool:
    return any(
        key in prompt_norm
        for key in ("parle moi en francais", "reponds en francais", "en francais")
    )


def _resolve_llm_budget_s(
    *,
    ask_and_speak_budget_seconds: float,
    qos: dict[str, Any],
    is_voice_request: bool,
) -> tuple[float, str]:
    mode = str(qos.get("mode", "NOMINAL")).upper()
    try:
        llm_budget_s = float(ask_and_speak_budget_seconds)
    except Exception:
        llm_budget_s = 3.2
    llm_budget_s = max(1.2, min(llm_budget_s, 6.0))
    if mode == "SURVIE":
        llm_budget_s = min(llm_budget_s, 2.0)
    elif mode == "TENDU":
        llm_budget_s = min(llm_budget_s, 2.4)
    elif not is_voice_request:
        llm_budget_s = min(llm_budget_s, 3.0)
    return llm_budget_s, mode


async def _handle_identity_query(
    *,
    backend_choice: dict[str, Any],
    ollama_config: OllamaConfig,
    orchestrator: Any,
    api_module: Any,
    is_voice_request: bool,
    task_type: str,
    deps: AskAndSpeakDeps,
) -> dict[str, Any]:
    model_name = str(
        backend_choice.get("recommended_model")
        or ollama_config.ask_model
        or ollama_config.model
    ).strip() or "inconnu"
    execution_backend = str(
        backend_choice.get("execution_backend")
        or backend_choice.get("preferred_backend")
        or "local_ollama"
    ).strip()
    response = f"Je suis Didier. Modele: {model_name}. Backend: {execution_backend}."
    response = deps.prepare_chat_text(
        response,
        orchestrator=orchestrator,
        qos=deps.runtime_qos_snapshot(),
    )
    return await _with_delivery(
        result={
            "response": response,
            "route": "local_info",
            "task_type": task_type,
            "routing": backend_choice,
        },
        response=response,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        deps=deps,
    )


async def _handle_local_status_query(
    *,
    backend_choice: dict[str, Any],
    orchestrator: Any,
    api_module: Any,
    is_voice_request: bool,
    task_type: str,
    deps: AskAndSpeakDeps,
) -> dict[str, Any]:
    qos = deps.runtime_qos_snapshot()
    mode_name = str(qos.get("mode", "NOMINAL")).upper()
    llm_profile = str(qos.get("llm_profile", "full")).lower() or "full"
    queue_size = int(qos.get("audio_queue_size", 0) or 0)
    speaking = bool(qos.get("audio_speaking", False))
    speaking_text = "oui" if speaking else "non"
    response = (
        f"Etat {mode_name}. Profil LLM {llm_profile}. "
        f"Audio en cours: {speaking_text}. File audio: {queue_size}."
    )
    response = deps.prepare_chat_text(
        response,
        orchestrator=orchestrator,
        qos=qos,
    )
    return await _with_delivery(
        result={
            "response": response,
            "route": "local_status",
            "task_type": task_type,
            "routing": backend_choice,
        },
        response=response,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        deps=deps,
    )


async def _handle_language_ack(
    *,
    backend_choice: dict[str, Any],
    orchestrator: Any,
    api_module: Any,
    is_voice_request: bool,
    task_type: str,
    deps: AskAndSpeakDeps,
) -> dict[str, Any]:
    response = "D'accord, je te reponds en francais."
    return await _with_delivery(
        result={
            "response": response,
            "task_type": task_type,
            "routing": backend_choice,
        },
        response=response,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        deps=deps,
    )


async def _handle_actuator_request(
    *,
    prompt_norm: str,
    backend_choice: dict[str, Any],
    orchestrator: Any,
    api_module: Any,
    is_voice_request: bool,
    task_type: str,
    deps: AskAndSpeakDeps,
) -> dict[str, Any] | None:
    actuators = orchestrator.get_tentacle("actuators")
    action = deps.parse_switch_action(prompt_norm)
    if not actuators or not action:
        return None
    try:
        devices = list(actuators.list_devices())
    except Exception:
        devices = []
    target = deps.resolve_actuator_target(prompt_norm, devices)
    if not target:
        return None
    actuator_id, actuator_name = target
    try:
        action_result = await api_module.asyncio.to_thread(
            actuators.command,
            actuator_id,
            action,
            {},
        )
    except Exception as exc:
        action_result = {"ok": False, "error": str(exc)}
    ok = bool(action_result.get("ok", False))
    if ok:
        verb = "allumee" if action == "on" else "eteinte"
        response = f"{actuator_name} {verb}."
    else:
        response = (
            f"Action impossible sur {actuator_name}: "
            f"{action_result.get('error', 'erreur inconnue')}"
        )
    return await _with_delivery(
        result={
            "response": response,
            "actuator": {
                "id": actuator_id,
                "name": actuator_name,
                "action": action,
                "ok": ok,
            },
            "task_type": task_type,
            "routing": backend_choice,
        },
        response=response,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        deps=deps,
    )


async def _handle_music_request(
    *,
    prompt: str,
    backend_choice: dict[str, Any],
    orchestrator: Any,
    api_module: Any,
    is_voice_request: bool,
    task_type: str,
    deps: AskAndSpeakDeps,
) -> dict[str, Any] | None:
    music = orchestrator.get_tentacle("music")
    if not music or not deps.is_music_prompt(prompt):
        return None
    await music.play(prompt)
    response = "Musique lancée."
    return await _with_delivery(
        result={
            "response": response,
            "music": True,
            "task_type": task_type,
            "routing": backend_choice,
        },
        response=response,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        deps=deps,
    )


async def handle_ask_and_speak(
    *,
    prompt: str,
    payload: dict[str, Any],
    orchestrator: Any,
    api_module: Any,
    arbitrator: Any,
    ollama_config: OllamaConfig,
    deps: AskAndSpeakDeps,
) -> dict[str, Any]:
    is_task_request, is_voice_request, is_web_request = _is_task_request(prompt, payload, deps)
    routed_payload = _routed_task_payload(
        payload,
        is_task_request=is_task_request,
        is_web_request=is_web_request,
    )
    if is_task_request:
        routed = await deps.process_input(
            prompt,
            is_voice=True,
            payload=routed_payload,
            orchestrator=orchestrator,
            api_module=api_module,
        )
        routed_response = str(routed.get("response", "")).strip()
        if routed_response:
            routed_response = deps.prepare_chat_text(
                routed_response,
                orchestrator=orchestrator,
                qos=deps.runtime_qos_snapshot(),
            )
            routed["response"] = routed_response
        return await _with_delivery(
            result=routed,
            response=routed_response,
            orchestrator=orchestrator,
            api_module=api_module,
            is_voice_request=is_voice_request,
            deps=deps,
        )

    clean_prompt, expert_model, expert_system, _expert = deps.resolve_expert_prompt(
        prompt,
        orchestrator.config,
    )
    task_type = deps.infer_task_type(clean_prompt, payload, is_task=False)
    backend_choice = deps.choose_backend(clean_prompt, task_type, payload)
    prompt_norm = deps.normalize_text(clean_prompt)

    if deps.looks_like_identity_query(prompt_norm):
        return await _handle_identity_query(
            backend_choice=backend_choice,
            ollama_config=ollama_config,
            orchestrator=orchestrator,
            api_module=api_module,
            is_voice_request=is_voice_request,
            task_type=task_type,
            deps=deps,
        )

    if deps.looks_like_local_status_query(prompt_norm):
        return await _handle_local_status_query(
            backend_choice=backend_choice,
            orchestrator=orchestrator,
            api_module=api_module,
            is_voice_request=is_voice_request,
            task_type=task_type,
            deps=deps,
        )

    if not arbitrator.request_resource("llm_generation"):
        response = "Je suis en surcharge temporaire. Reessaie dans quelques secondes."
        result = await _with_delivery(
            result={"response": response, "task_type": task_type},
            response=response,
            orchestrator=orchestrator,
            api_module=api_module,
            is_voice_request=is_voice_request,
            deps=deps,
        )
        result["routing"] = {
            "task_type": task_type,
            "route_hint": "arbitration_guard",
            "execution_backend": "none",
            "fallback_active": True,
            "fallback_reason": "arbitration_denied:llm_generation",
        }
        return result

    if _language_ack_requested(prompt_norm):
        return await _handle_language_ack(
            backend_choice=backend_choice,
            orchestrator=orchestrator,
            api_module=api_module,
            is_voice_request=is_voice_request,
            task_type=task_type,
            deps=deps,
        )

    actuator_result = await _handle_actuator_request(
        prompt_norm=prompt_norm,
        backend_choice=backend_choice,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        task_type=task_type,
        deps=deps,
    )
    if actuator_result is not None:
        return actuator_result

    music_result = await _handle_music_request(
        prompt=prompt,
        backend_choice=backend_choice,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        task_type=task_type,
        deps=deps,
    )
    if music_result is not None:
        return music_result

    qos = deps.runtime_qos_snapshot()
    llm_budget_s, mode = _resolve_llm_budget_s(
        ask_and_speak_budget_seconds=ollama_config.ask_and_speak_budget_seconds,
        qos=qos,
        is_voice_request=is_voice_request,
    )

    try:
        generation_payload = dict(payload)
        generation_payload["llm_budget_s"] = llm_budget_s
        generated = await asyncio.wait_for(
            deps.generate_conversation_response(
                clean_prompt=clean_prompt,
                task_type=task_type,
                expert_model=expert_model,
                expert_system=expert_system,
                backend_choice=backend_choice,
                payload=generation_payload,
                orchestrator=orchestrator,
                api_module=api_module,
            ),
            timeout=llm_budget_s,
        )
    except asyncio.TimeoutError:
        response = "Je suis en charge. Reessaie dans quelques secondes."
        backend_choice["fallback_active"] = True
        backend_choice["fallback_reason"] = f"ask_and_speak_budget_timeout:{llm_budget_s:.1f}s"
        backend_choice["arbitration_mode"] = mode
        result = await _with_delivery(
            result={
                "response": response,
                "route": "stub",
                "task_type": task_type,
                "routing": backend_choice,
            },
            response=response,
            orchestrator=orchestrator,
            api_module=api_module,
            is_voice_request=is_voice_request,
            deps=deps,
        )
        return result

    response = str(generated.get("response", "")).strip()
    if not response:
        response = "Je suis encore en charge. Reessaie dans quelques secondes."
    response = deps.prepare_chat_text(
        response,
        orchestrator=orchestrator,
        qos=qos,
    )
    backend_choice = generated.get("routing", backend_choice)
    result: dict[str, Any] = {
        "response": response,
        "task_type": task_type,
        "routing": backend_choice,
    }
    route = str(generated.get("route", "")).strip()
    model = str(generated.get("model", "")).strip()
    if route:
        result["route"] = route
    if model:
        result["model"] = model
    result = await _with_delivery(
        result=result,
        response=response,
        orchestrator=orchestrator,
        api_module=api_module,
        is_voice_request=is_voice_request,
        deps=deps,
    )
    return result
