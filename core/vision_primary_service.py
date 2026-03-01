"""Primary vision detections cache and fallback helpers."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any
from typing import Mapping

from core.vision_secondary_service import enrich_detection_shapes


@dataclass
class PrimaryDetectionsState:
    cache_ttl_s: float = 0.7
    last_payload_ts: float = 0.0
    last_payload: dict[str, Any] | None = None
    last_non_empty_ts: float = 0.0
    last_non_empty_payload: dict[str, Any] | None = None
    non_empty_hold_ttl_s: float = 1.2

    def hold_last_non_empty_payload(
        self,
        now: float,
        *,
        source: str = "primary_hold_non_empty",
    ) -> dict[str, Any] | None:
        if self.last_non_empty_payload is None:
            return None
        if (float(now) - float(self.last_non_empty_ts)) > float(self.non_empty_hold_ttl_s):
            return None
        held = enrich_detection_shapes(copy.deepcopy(self.last_non_empty_payload))
        held["source"] = str(source)
        return held

    def fresh_cached_payload(self, now: float, *, source: str) -> dict[str, Any] | None:
        if self.last_payload is None:
            return None
        if (float(now) - float(self.last_payload_ts)) >= float(self.cache_ttl_s):
            return None
        cached_detections = self.last_payload.get("detections", [])
        if isinstance(cached_detections, list) and not cached_detections:
            held = self.hold_last_non_empty_payload(now)
            if held is not None:
                return held
        cached = enrich_detection_shapes(copy.deepcopy(self.last_payload))
        cached["source"] = str(source)
        return cached

    def cached_payload(self, *, source: str) -> dict[str, Any] | None:
        if self.last_payload is None:
            return None
        cached_detections = self.last_payload.get("detections", [])
        if isinstance(cached_detections, list) and not cached_detections:
            held = self.hold_last_non_empty_payload(self.last_payload_ts)
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
    ) -> dict[str, Any]:
        data = dict(payload or {})
        if not isinstance(data, dict):
            data = {}
        if not isinstance(data.get("detections"), list):
            data = {
                "detections": [],
                "frame": {"width": None, "height": None},
                "ts": 0.0,
            }
        enriched = enrich_detection_shapes(data)
        self.last_payload = copy.deepcopy(enriched)
        self.last_payload_ts = float(refreshed_at)
        detections = enriched.get("detections", [])
        if isinstance(detections, list) and detections:
            self.last_non_empty_payload = copy.deepcopy(enriched)
            self.last_non_empty_ts = float(refreshed_at)
            return enriched
        held = self.hold_last_non_empty_payload(float(refreshed_at))
        if held is not None:
            return held
        return enriched

    def empty_payload(self, *, source: str) -> dict[str, Any]:
        return {
            "detections": [],
            "frame": {"width": None, "height": None},
            "ts": 0.0,
            "source": str(source),
        }
