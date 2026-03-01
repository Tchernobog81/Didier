"""Model selection helpers for system routes."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_task_type(value: Any) -> str:
    return str(value or "").strip().lower()


def read_runtime_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def write_runtime_config(config_path: Path, payload: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = config_path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    tmp_path.replace(config_path)


def build_current_models_payload(config_root: dict[str, Any]) -> dict[str, Any]:
    root = _as_dict(config_root)
    ollama_cfg = _as_dict(root.get("ollama"))
    profiles = _as_dict(ollama_cfg.get("model_profiles"))
    llmfit_cfg = _as_dict(root.get("llmfit"))
    llmfit_profiles = _as_dict(llmfit_cfg.get("task_profiles"))
    llmfit_models: dict[str, dict[str, Any]] = {}
    for task_name in ("chat", "coding", "react_task", "vision", "asr", "tts"):
        task_cfg = _as_dict(llmfit_profiles.get(task_name))
        if not task_cfg:
            continue
        llmfit_models[task_name] = {
            "backend": str(task_cfg.get("backend", "")).strip() or None,
            "model": str(task_cfg.get("model", "")).strip() or None,
            "score": str(task_cfg.get("score", "")).strip() or None,
        }
    return {
        "default": str(ollama_cfg.get("model", "")).strip() or None,
        "ask": str(profiles.get("ask", "")).strip() or None,
        "coding": str(profiles.get("coding", "")).strip() or None,
        "selected_at": float(ollama_cfg.get("model_selected_at", 0.0) or 0.0),
        "llmfit_profiles": llmfit_models,
    }


def find_llmfit_recommendation(
    report: dict[str, Any],
    task_type: str,
    model: str,
) -> dict[str, Any] | None:
    normalized_task = normalize_task_type(task_type)
    normalized_model = str(model or "").strip()
    if not normalized_task or not normalized_model:
        return None
    recommendations = report.get("recommendations", [])
    if not isinstance(recommendations, list):
        return None
    for entry in recommendations:
        if not isinstance(entry, dict):
            continue
        task_entry = normalize_task_type(entry.get("task_type"))
        model_entry = str(entry.get("model", "")).strip()
        if task_entry == normalized_task and model_entry == normalized_model:
            return dict(entry)
    return None


@dataclass(frozen=True)
class ModelSelectionRequest:
    task_type: str
    model: str
    backend: str | None
    allow_unbenchmarked: bool = False


@dataclass(frozen=True)
class ModelSelectionError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def parse_model_selection_request(
    payload: dict[str, Any] | None,
    *,
    selectable_tasks: set[str],
) -> ModelSelectionRequest:
    body = payload or {}
    task_type = normalize_task_type(body.get("task_type"))
    model = str(body.get("model", "")).strip()
    backend = str(body.get("backend", "")).strip() or None
    allow_unbenchmarked = bool(body.get("allow_unbenchmarked", False))

    if not task_type:
        raise ModelSelectionError(status_code=400, detail="task_type required")
    if task_type not in selectable_tasks:
        raise ModelSelectionError(
            status_code=400,
            detail=f"task_type not selectable: {task_type}",
        )
    if not model:
        raise ModelSelectionError(status_code=400, detail="model required")
    if len(model) > 160 or any(ch in model for ch in ("\n", "\r", "\x00")):
        raise ModelSelectionError(status_code=400, detail="invalid model value")

    return ModelSelectionRequest(
        task_type=task_type,
        model=model,
        backend=backend,
        allow_unbenchmarked=allow_unbenchmarked,
    )


def apply_model_selection(
    config_root: dict[str, Any],
    request: ModelSelectionRequest,
    recommendation: dict[str, Any] | None,
    *,
    selected_at: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not config_root:
        raise ModelSelectionError(status_code=503, detail="runtime config unavailable")

    root = copy.deepcopy(_as_dict(config_root))
    llmfit_cfg = _as_dict(root.setdefault("llmfit", {}))
    llmfit_profiles = _as_dict(llmfit_cfg.setdefault("task_profiles", {}))
    task_profile = _as_dict(llmfit_profiles.setdefault(request.task_type, {}))
    task_profile["model"] = request.model
    if request.backend:
        task_profile["backend"] = request.backend
    elif recommendation is not None:
        task_profile["backend"] = (
            str(recommendation.get("backend", "")).strip() or task_profile.get("backend")
        )
    if recommendation is not None:
        score = str(recommendation.get("score", "")).strip()
        if score:
            task_profile["score"] = score
    llmfit_profiles[request.task_type] = task_profile
    llmfit_cfg["task_profiles"] = llmfit_profiles
    root["llmfit"] = llmfit_cfg

    ollama_cfg = _as_dict(root.setdefault("ollama", {}))
    model_profiles = _as_dict(ollama_cfg.setdefault("model_profiles", {}))
    if request.task_type in {"chat", "react_task"}:
        model_profiles["ask"] = request.model
        ollama_cfg["model"] = request.model
    elif request.task_type == "coding":
        model_profiles["coding"] = request.model
    ollama_cfg["model_profiles"] = model_profiles
    ollama_cfg["model_selected_at"] = float(selected_at)
    root["ollama"] = ollama_cfg

    applied = {
        "task_type": request.task_type,
        "model": request.model,
        "backend": request.backend
        or (str(recommendation.get("backend", "")).strip() if recommendation else None),
        "benchmarked": recommendation is not None,
        "score": str(recommendation.get("score", "")).strip() if recommendation else None,
    }
    return root, applied
