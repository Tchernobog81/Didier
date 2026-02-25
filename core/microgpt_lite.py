"""MicroGPT-lite: tiny statistical supervisor for Edge runtime.

Goal:
- Keep a very small "little brain" always-on.
- Detect anomalies from lightweight telemetry.
- Decide whether waking Ollama is necessary.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import re
import time
from typing import Any


@dataclass
class Decision:
    wake_ollama: bool
    reason: str
    quick_response: str | None = None


class MicroGPTLite:
    def __init__(self, window_size: int = 180) -> None:
        self._samples: deque[dict[str, Any]] = deque(maxlen=max(30, window_size))
        self._anomaly_events = 0
        self._last_anomaly: dict[str, Any] | None = None

    def _normalize(self, text: str) -> str:
        lowered = (text or "").strip().lower()
        lowered = re.sub(r"\s+", " ", lowered)
        return lowered

    def ingest(self, sample: dict[str, Any]) -> dict[str, Any]:
        now = time.time()
        payload = dict(sample)
        payload["ts"] = now

        score = 0
        reasons: list[str] = []

        load1 = payload.get("load1")
        if isinstance(load1, (int, float)):
            if load1 >= 1.5:
                score += 2
                reasons.append("load_high")
            elif load1 >= 1.0:
                score += 1
                reasons.append("load_warn")

        workers = payload.get("workers") or {}
        if isinstance(workers, dict):
            down = [k for k, v in workers.items() if not bool(v)]
            critical_down = [k for k in down if k in {"vision", "audio"}]
            if critical_down:
                score += min(3, len(critical_down))
                reasons.append("workers_degraded")
                payload["workers_down"] = critical_down

        response_p95_ms = payload.get("response_p95_ms")
        if isinstance(response_p95_ms, (int, float)):
            if response_p95_ms >= 1200:
                score += 2
                reasons.append("latency_high")
            elif response_p95_ms >= 600:
                score += 1
                reasons.append("latency_warn")

        payload["anomaly_score"] = score
        payload["anomaly_reasons"] = reasons
        self._samples.append(payload)

        if score >= 2:
            self._anomaly_events += 1
            self._last_anomaly = {
                "ts": now,
                "score": score,
                "reasons": reasons,
                "workers_down": payload.get("workers_down", []),
            }
        return payload

    def status(self) -> dict[str, Any]:
        latest = self._samples[-1] if self._samples else None
        return {
            "samples": len(self._samples),
            "anomaly_events": self._anomaly_events,
            "last_anomaly": self._last_anomaly,
            "latest_score": latest.get("anomaly_score", 0) if latest else 0,
            "latest_reasons": latest.get("anomaly_reasons", []) if latest else [],
        }

    def _quick_response(self, prompt: str, telemetry: dict[str, Any]) -> str | None:
        p = self._normalize(prompt)
        if not p:
            return "Dis-moi ce que tu veux faire."

        if any(token in p for token in ["bonjour", "salut", "hello", "yo didier", "yo didier!"]):
            return "Salut. Je suis en veille active."

        if any(token in p for token in ["status", "etat", "état", "health", "sante", "santé"]):
            workers = telemetry.get("workers") or {}
            if isinstance(workers, dict):
                down = [k for k, ok in workers.items() if not bool(ok)]
            else:
                down = []
            if down:
                return f"État dégradé: {', '.join(down)} indisponible(s)."
            return "État OK: workers en ligne."

        if any(token in p for token in ["heure", "time"]):
            return time.strftime("Il est %H:%M:%S.")

        if any(token in p for token in ["ping", "test rapide", "quick test"]):
            return "Ping OK."

        return None

    def decide(self, prompt: str, telemetry: dict[str, Any]) -> Decision:
        p = self._normalize(prompt)

        quick = self._quick_response(p, telemetry)
        if quick is not None:
            return Decision(wake_ollama=False, reason="handled_by_micro", quick_response=quick)

        complex_tokens = [
            "pourquoi",
            "explique",
            "compare",
            "analyse",
            "plan",
            "résume",
            "resume",
            "code",
            "script",
            "architecture",
            "optimise",
            "optimiser",
        ]
        if "?" in p or len(p) >= 80 or any(t in p for t in complex_tokens):
            return Decision(wake_ollama=True, reason="complex_prompt")

        latest_score = 0
        if self._samples:
            latest_score = int(self._samples[-1].get("anomaly_score", 0) or 0)
        if latest_score >= 2:
            return Decision(wake_ollama=True, reason="runtime_anomaly")

        # Default: cheap local response for short/simple text.
        return Decision(
            wake_ollama=False,
            reason="simple_prompt",
            quick_response="Commande reçue. Je reste en mode léger.",
        )
