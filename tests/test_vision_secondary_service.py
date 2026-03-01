import unittest

from core.vision_secondary_service import SecondaryDetectionsState
from core.vision_secondary_service import enrich_detection_shapes
from core.vision_secondary_service import secondary_empty_payload
from core.vision_secondary_service import secondary_min_interval_s


class _Arbitrator:
    def __init__(self, mode: str, target_fps: int = 20) -> None:
        self._mode = mode
        self._target_fps = target_fps

    def snapshot(self) -> dict[str, object]:
        return {"mode": self._mode, "limits": {"target_fps": self._target_fps}}


class VisionSecondaryServiceTests(unittest.TestCase):
    def test_enrich_detection_shapes_adds_shape_from_polygon(self) -> None:
        payload = {
            "detections": [
                {
                    "label": "objet",
                    "poly": [[0, 0], [10, 0], [10, 10], [0, 10]],
                }
            ]
        }

        enriched = enrich_detection_shapes(payload)

        self.assertEqual(enriched["detections"][0]["shape"], "quadrilatere")

    def test_secondary_min_interval_s_respects_arbitration_mode(self) -> None:
        self.assertEqual(secondary_min_interval_s(_Arbitrator("NOMINAL", target_fps=20)), 0.12)
        self.assertEqual(secondary_min_interval_s(_Arbitrator("TENDU", target_fps=10)), 0.2)
        self.assertEqual(secondary_min_interval_s(_Arbitrator("SURVIE", target_fps=6)), 1.25)

    def test_secondary_state_prefers_recent_non_empty_hold_when_cache_is_empty(self) -> None:
        state = SecondaryDetectionsState(non_empty_hold_ttl_s=4.0)
        state.last_payload = {"detections": [], "status": {"state": "empty"}}
        state.last_non_empty_payload = {
            "detections": [{"label": "personne"}],
            "status": {"state": "ok"},
            "stream_ts": 1.0,
        }
        state.last_non_empty_ts = 10.0

        held = state.response_from_cached(
            12.0,
            source="secondary_cache",
            stream_ts=3.0,
            hold_state_reason="hold_last_non_empty:test",
        )

        self.assertEqual(held["source"], "secondary_hold_non_empty")
        self.assertEqual(held["status"]["state"], "hold_last_non_empty:test")
        self.assertEqual(held["stream_ts"], 3.0)
        self.assertEqual(held["detections"][0]["label"], "personne")

    def test_finalize_fresh_payload_updates_state_and_holds_on_empty(self) -> None:
        state = SecondaryDetectionsState(non_empty_hold_ttl_s=4.0)
        state.last_non_empty_payload = {
            "detections": [{"label": "voiture"}],
            "status": {"state": "ok"},
        }
        state.last_non_empty_ts = 5.0

        result = state.finalize_fresh_payload(
            {
                "detections": [],
                "status": {"state": "empty"},
            },
            refreshed_at=6.0,
            stream_ts=2.5,
        )

        self.assertEqual(result["source"], "secondary_hold_non_empty")
        self.assertEqual(state.last_refresh_ts, 6.0)
        self.assertEqual(state.last_payload["detections"], [])

    def test_secondary_empty_payload_keeps_reason_and_stream_ts(self) -> None:
        payload = secondary_empty_payload("secondary timeout", stream_ts=7.2)

        self.assertEqual(payload["status"]["state"], "secondary timeout")
        self.assertEqual(payload["stream_ts"], 7.2)
        self.assertEqual(payload["source"], "secondary_empty")


if __name__ == "__main__":
    unittest.main()
