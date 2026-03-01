"""State and payload policy helpers for secondary vision detections."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any
from typing import Mapping


def _shape_from_poly(poly: list[Any]) -> str:
    points = [pt for pt in poly if isinstance(pt, (list, tuple)) and len(pt) >= 2]
    count = len(points)
    if count <= 2:
        return "segment"
    if count == 3:
        return "triangle"
    if count == 4:
        return "quadrilatere"
    if count <= 7:
        return "polygone"
    return "arrondi"


def enrich_detection_shapes(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    data = dict(payload or {})
    detections = data.get("detections", [])
    if not isinstance(detections, list):
        data["detections"] = []
        return data
    enriched: list[dict[str, Any]] = []
    for item in detections:
        if not isinstance(item, Mapping):
            continue
        det = dict(item)
        poly = det.get("poly", [])
        if isinstance(poly, list) and len(poly) >= 3 and not det.get("shape"):
            det["shape"] = _shape_from_poly(poly)
        enriched.append(det)
    data["detections"] = enriched
    return data


def secondary_empty_payload(reason: str, stream_ts: float = 0.0) -> dict[str, Any]:
    return {
        "detections": [],
        "frame": {"width": None, "height": None},
        "ts": 0.0,
        "stream_ts": float(stream_ts or 0.0),
        "status": {"state": str(reason)},
        "source": "secondary_empty",
    }


def secondary_min_interval_s(
    arbitrator: Any,
    *,
    nominal_s: float = 0.25,
    tendu_s: float = 0.4,
    survie_s: float = 1.25,
) -> float:
    try:
        snap = arbitrator.snapshot()
    except Exception:
        snap = {}
    limits = (snap or {}).get("limits", {})
    target_fps = 0.0
    if isinstance(limits, Mapping):
        try:
            target_fps = float(limits.get("target_fps", 0.0) or 0.0)
        except Exception:
            target_fps = 0.0
    paced_interval = None
    if target_fps > 0.0:
        paced_interval = max(0.12, min(0.5, 2.0 / target_fps))
    mode = str((snap or {}).get("mode", "NOMINAL")).upper()
    if mode == "SURVIE":
        return float(survie_s)
    if mode == "TENDU":
        base = float(tendu_s)
    else:
        base = float(nominal_s)
    if paced_interval is None:
        return base
    return min(base, float(paced_interval))


@dataclass
class SecondaryDetectionsState:
    last_refresh_ts: float = 0.0
    last_payload: dict[str, Any] | None = None
    last_non_empty_ts: float = 0.0
    last_non_empty_payload: dict[str, Any] | None = None
    non_empty_hold_ttl_s: float = 4.0

    def hold_last_non_empty_payload(
        self,
        now: float,
        *,
        stream_ts: float = 0.0,
        state_reason: str = "hold_last_non_empty",
    ) -> dict[str, Any] | None:
        if self.last_non_empty_payload is None:
            return None
        if (now - self.last_non_empty_ts) > float(self.non_empty_hold_ttl_s):
            return None
        held = enrich_detection_shapes(copy.deepcopy(self.last_non_empty_payload))
        held["stream_ts"] = float(stream_ts or held.get("stream_ts", 0.0) or 0.0)
        status = held.get("status")
        if not isinstance(status, dict):
            status = {}
        status["state"] = str(state_reason)
        held["status"] = status
        held["source"] = "secondary_hold_non_empty"
        return held

    def response_from_cached(
        self,
        now: float,
        *,
        source: str,
        stream_ts: float = 0.0,
        hold_state_reason: str = "hold_last_non_empty",
    ) -> dict[str, Any] | None:
        if self.last_payload is None:
            return None
        cached_detections = self.last_payload.get("detections", [])
        if isinstance(cached_detections, list) and not cached_detections:
            held = self.hold_last_non_empty_payload(
                now,
                stream_ts=stream_ts,
                state_reason=hold_state_reason,
            )
            if held is not None:
                return held
        cached = enrich_detection_shapes(copy.deepcopy(self.last_payload))
        cached["source"] = str(source)
        return cached

    def finalize_fresh_payload(
        self,
        payload: Mapping[str, Any] | None,
        *,
        refreshed_at: float,
        stream_ts: float = 0.0,
    ) -> dict[str, Any]:
        data = enrich_detection_shapes(payload)
        self.last_payload = copy.deepcopy(data)
        self.last_refresh_ts = float(refreshed_at)
        detections = data.get("detections", [])
        if isinstance(detections, list) and detections:
            self.last_non_empty_payload = copy.deepcopy(data)
            self.last_non_empty_ts = float(refreshed_at)
            return data
        held = self.hold_last_non_empty_payload(
            float(refreshed_at),
            stream_ts=stream_ts,
        )
        if held is not None:
            return held
        return data
