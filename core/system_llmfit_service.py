"""LLMFit report aggregation and cache orchestration for system routes."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from dataclasses import field
from typing import Any
from typing import Callable


DEFAULT_LLMFIT_TASK_SAMPLES: tuple[tuple[str, str], ...] = (
    ("chat", "Bonjour Didier, fais un point rapide du systeme."),
    ("coding", "Ecris une fonction Python fibonacci iterative."),
    ("vision", "Detecte les objets visibles dans le flux camera."),
    ("asr", "Transcrire une commande vocale courte."),
    ("tts", "Synthese vocale courte et claire."),
    ("react_task", "Allume la lumiere du salon."),
)


def llmfit_score_bucket(score: str) -> str:
    normalized = str(score or "").strip().lower()
    if "perfect" in normalized:
        return "perfect"
    if "good" in normalized:
        return "good"
    if "marginal" in normalized:
        return "marginal"
    return "fallback"


def llmfit_reason_excerpt(reason: str, limit: int = 220) -> str:
    text = str(reason or "").strip()
    if len(text) <= int(limit):
        return text
    return text[: max(0, int(limit) - 3)].rstrip() + "..."


def llmfit_context_from_state(state: dict[str, Any]) -> dict[str, Any]:
    metrics = state.get("metrics", {}) if isinstance(state, dict) else {}
    hardware_profile = state.get("hardware_profile", {}) if isinstance(state, dict) else {}
    npu = hardware_profile.get("npu", {}) if isinstance(hardware_profile, dict) else {}
    tpu = hardware_profile.get("tpu", {}) if isinstance(hardware_profile, dict) else {}
    cpu = metrics.get("cpu", {}) if isinstance(metrics, dict) else {}
    memory = metrics.get("memory", {}) if isinstance(metrics, dict) else {}
    return {
        "npu_available": bool(npu.get("available", False)),
        "npu_device_count": int(npu.get("device_count", 0) or 0),
        "pixel_detected": bool(tpu.get("pixel_detected", False)),
        "pixel_count": int(tpu.get("pixel_count", 0) or 0),
        "cpu_percent": float(cpu.get("percent", 0.0) or 0.0),
        "memory_percent": float(memory.get("percent", 0.0) or 0.0),
    }


def build_llmfit_recommendation(
    task_type: str,
    prompt_sample: str,
    base_context: dict[str, Any],
    *,
    get_best_model: Callable[[str, dict[str, Any]], dict[str, Any]],
    default_timeout_s: float,
    now: Callable[[], float],
) -> dict[str, Any]:
    context = dict(base_context)
    context["prompt_preview"] = str(prompt_sample or "")[:120]
    context["task_sample"] = str(task_type or "")
    result = get_best_model(task_type, context)
    score = str(result.get("score", "good")).strip().lower()
    return {
        "task_type": str(task_type or "").strip() or "chat",
        "prompt_sample": str(prompt_sample or ""),
        "backend": str(result.get("backend", "")).strip(),
        "model": str(result.get("model", "")).strip(),
        "score": score or "good",
        "score_bucket": llmfit_score_bucket(score),
        "provider": str(result.get("provider", "llmfit")).strip() or "llmfit",
        "source": str(result.get("source", "fallback")).strip() or "fallback",
        "reason": llmfit_reason_excerpt(str(result.get("reason", ""))),
        "timeout_s": float(result.get("timeout_s", default_timeout_s) or default_timeout_s),
        "ts": float(result.get("ts", now()) or now()),
    }


def _empty_summary() -> dict[str, int]:
    return {
        "tasks_total": 0,
        "llmfit_hits": 0,
        "fallback_hits": 0,
        "perfect": 0,
        "good": 0,
        "marginal": 0,
        "fallback": 0,
    }


@dataclass
class LLMFitReportCollector:
    cache_ttl_s: float
    task_samples: tuple[tuple[str, str], ...] = DEFAULT_LLMFIT_TASK_SAMPLES
    read_shared_state_fn: Callable[[], dict[str, Any]] | None = None
    get_best_model_fn: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    default_timeout_s: float = 2.0
    now: Callable[[], float] = time.time
    _cache: dict[str, Any] | None = None
    _cache_ts: float = 0.0
    _lock: Any = field(default_factory=asyncio.Lock)

    def invalidate(self) -> None:
        self._cache = None
        self._cache_ts = 0.0

    async def collect(self, *, force: bool) -> dict[str, Any]:
        current = float(self.now())
        if not force and self._cache is not None and (current - self._cache_ts) <= self.cache_ttl_s:
            return dict(self._cache)
        if self._lock.locked() and self._cache is not None and not force:
            return dict(self._cache)

        async with self._lock:
            current = float(self.now())
            if not force and self._cache is not None and (current - self._cache_ts) <= self.cache_ttl_s:
                return dict(self._cache)
            try:
                if self.read_shared_state_fn is None or self.get_best_model_fn is None:
                    raise RuntimeError("llmfit collector dependencies not configured")
                state = self.read_shared_state_fn()
                hardware_profile = state.get("hardware_profile", {}) if isinstance(state, dict) else {}
                base_context = llmfit_context_from_state(state if isinstance(state, dict) else {})
                jobs = [
                    asyncio.to_thread(
                        build_llmfit_recommendation,
                        task,
                        prompt,
                        base_context,
                        get_best_model=self.get_best_model_fn,
                        default_timeout_s=self.default_timeout_s,
                        now=self.now,
                    )
                    for task, prompt in self.task_samples
                ]
                recommendations = await asyncio.gather(*jobs)
                bucket_counts: dict[str, int] = {
                    "perfect": 0,
                    "good": 0,
                    "marginal": 0,
                    "fallback": 0,
                }
                llmfit_hits = 0
                fallback_hits = 0
                for item in recommendations:
                    bucket = str(item.get("score_bucket", "fallback"))
                    if bucket not in bucket_counts:
                        bucket = "fallback"
                    bucket_counts[bucket] += 1
                    if str(item.get("source", "")) == "llmfit":
                        llmfit_hits += 1
                    else:
                        fallback_hits += 1
                payload = {
                    "ok": True,
                    "ts": float(self.now()),
                    "status": "running" if llmfit_hits > 0 else "degraded",
                    "provider": "llmfit",
                    "cache_ttl_s": float(self.cache_ttl_s),
                    "summary": {
                        "tasks_total": len(recommendations),
                        "llmfit_hits": llmfit_hits,
                        "fallback_hits": fallback_hits,
                        **bucket_counts,
                    },
                    "hardware_profile": hardware_profile if isinstance(hardware_profile, dict) else {},
                    "recommendations": recommendations,
                }
            except Exception as exc:
                payload = {
                    "ok": False,
                    "ts": float(self.now()),
                    "status": "offline",
                    "provider": "llmfit",
                    "cache_ttl_s": float(self.cache_ttl_s),
                    "summary": _empty_summary(),
                    "hardware_profile": {},
                    "recommendations": [],
                    "error": str(exc),
                }
            self._cache = dict(payload)
            self._cache_ts = float(self.now())
            return payload
