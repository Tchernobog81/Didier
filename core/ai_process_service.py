"""Input processing service for AI routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Awaitable
from typing import Callable


@dataclass(frozen=True)
class ProcessInputDeps:
    resolve_expert_prompt: Callable[[str, object], tuple[str, str | None, str | None, Any]]
    vision_see_user: Callable[[float], Awaitable[dict[str, Any] | None]]
    vision_glance_text: Callable[[dict[str, Any] | None], str]
    looks_like_web_query: Callable[[str], bool]
    looks_like_task_request: Callable[..., bool]
    infer_task_type: Callable[..., str]
    choose_backend: Callable[[str, str, dict[str, Any]], dict[str, Any]]
    relay_picobot_react: Callable[..., Awaitable[dict[str, Any] | None]]
    extract_agent_reply: Callable[[dict[str, Any] | None], str]
    build_task_apology: Callable[[str], str]
    prepend_glance: Callable[[str, str], str]
    generate_conversation_response: Callable[..., Awaitable[dict[str, Any]]]


async def process_input(
    *,
    prompt: str,
    is_voice: bool = False,
    image_bytes: bytes | None = None,
    payload: dict[str, Any] | None = None,
    orchestrator: Any,
    api_module: Any,
    deps: ProcessInputDeps,
) -> dict[str, Any]:
    _ = image_bytes  # Reserved for the vision-aware path.
    payload = payload or {}

    clean_prompt, expert_model, expert_system, _expert = deps.resolve_expert_prompt(
        prompt,
        orchestrator.config,
    )
    vision_glance_payload: dict[str, Any] | None = None
    if bool(payload.get("vision_glance", True)):
        vision_timeout_s = float(payload.get("vision_timeout_s", 0.8))
        vision_glance_payload = await deps.vision_see_user(vision_timeout_s)
    glance_text = deps.vision_glance_text(vision_glance_payload)

    force_task = bool(payload.get("force_task", False))
    web_query = bool(payload.get("web_query", False)) or deps.looks_like_web_query(clean_prompt)
    is_task = force_task or web_query or deps.looks_like_task_request(
        clean_prompt,
        is_voice=is_voice,
    )
    task_type = deps.infer_task_type(clean_prompt, payload, is_task=is_task)
    backend_choice = deps.choose_backend(clean_prompt, task_type, payload)

    if is_task:
        react_payload = dict(payload)
        react_payload["react_filter"] = True
        react_payload["task_type"] = task_type
        react_payload["web_query"] = bool(web_query)
        react_result = await deps.relay_picobot_react(
            payload=react_payload,
            prompt=clean_prompt,
            orchestrator=orchestrator,
            api_module=api_module,
        )
        react_text = deps.extract_agent_reply(react_result)
        if not react_text and isinstance(react_result, dict) and react_result.get("ok", False):
            react_text = "Tache Picobot en cours."
        if not react_text:
            error_msg = (
                str((react_result or {}).get("error", "")).strip()
                if isinstance(react_result, dict)
                else ""
            )
            react_text = deps.build_task_apology(error_msg)
        react_text = deps.prepend_glance(react_text, glance_text)
        return {
            "response": react_text,
            "task": True,
            "route": "picobot",
            "task_type": task_type,
            "routing": backend_choice,
            "react": react_result,
            "vision": vision_glance_payload,
            "source": "process_input",
        }

    result = await deps.generate_conversation_response(
        clean_prompt=clean_prompt,
        task_type=task_type,
        expert_model=expert_model,
        expert_system=expert_system,
        backend_choice=backend_choice,
        payload=payload,
        orchestrator=orchestrator,
        api_module=api_module,
    )
    result["response"] = deps.prepend_glance(str(result.get("response", "")), glance_text)
    result["vision"] = vision_glance_payload
    result["source"] = "process_input"
    return result
