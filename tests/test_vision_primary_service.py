import unittest

from core.vision_primary_service import PrimaryDetectionsState


class VisionPrimaryServiceTests(unittest.TestCase):
    def test_fresh_cached_payload_respects_ttl(self) -> None:
        state = PrimaryDetectionsState(
            cache_ttl_s=0.7,
            last_payload_ts=10.0,
            last_payload={"detections": [{"poly": [[0, 0], [1, 0], [1, 1], [0, 1]]}]},
        )

        cached = state.fresh_cached_payload(10.3, source="primary_cache")
        stale = state.fresh_cached_payload(10.8, source="primary_cache")

        self.assertIsNotNone(cached)
        self.assertEqual(cached["source"], "primary_cache")
        self.assertEqual(cached["detections"][0]["shape"], "quadrilatere")
        self.assertIsNone(stale)

    def test_cached_payload_returns_copy_when_available(self) -> None:
        state = PrimaryDetectionsState(last_payload={"detections": []})

        cached = state.cached_payload(source="primary_error_cache")

        self.assertEqual(cached["source"], "primary_error_cache")
        self.assertEqual(cached["detections"], [])

    def test_finalize_fresh_payload_updates_state(self) -> None:
        state = PrimaryDetectionsState()

        result = state.finalize_fresh_payload(
            {"detections": [{"label": "objet"}], "frame": {"width": 10, "height": 10}, "ts": 1.0},
            refreshed_at=5.0,
        )

        self.assertEqual(result["detections"][0]["label"], "objet")
        self.assertEqual(state.last_payload_ts, 5.0)
        self.assertEqual(state.last_payload["frame"]["width"], 10)

    def test_empty_payload_is_standardized(self) -> None:
        state = PrimaryDetectionsState()

        payload = state.empty_payload(source="primary_timeout")

        self.assertEqual(payload["source"], "primary_timeout")
        self.assertEqual(payload["detections"], [])
        self.assertEqual(payload["ts"], 0.0)


if __name__ == "__main__":
    unittest.main()
