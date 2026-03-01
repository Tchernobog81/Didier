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

    def fresh_cached_payload(self, now: float, *, source: str) -> dict[str, Any] | None:
        if self.last_payload is None:
            return None
        if (float(now) - float(self.last_payload_ts)) >= float(self.cache_ttl_s):
            return None
        cached = enrich_detection_shapes(copy.deepcopy(self.last_payload))
        cached["source"] = str(source)
        return cached

    def cached_payload(self, *, source: str) -> dict[str, Any] | None:
        if self.last_payload is None:
            return None
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
        return enriched

    def empty_payload(self, *, source: str) -> dict[str, Any]:
        return {
            "detections": [],
            "frame": {"width": None, "height": None},
            "ts": 0.0,
            "source": str(source),
        }
