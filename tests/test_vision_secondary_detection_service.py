import asyncio
import unittest

from core.vision_secondary_detection_service import VisionSecondaryDetectionDeps
from core.vision_secondary_detection_service import collect_secondary_detections
from core.vision_secondary_service import SecondaryDetectionsState
from core.vision_stream_service import SecondaryStreamConfig


class _Arbitrator:
    def __init__(self, mode: str = "NOMINAL") -> None:
        self._mode = mode

    def snapshot(self) -> dict[str, str]:
        return {"mode": self._mode}


class _Vision:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def detect_secondary_frame(self, frame: object) -> dict[str, object]:
        self.calls.append(str(frame))
        return {"detections": [{"label": "personne"}], "frame": {"width": 10, "height": 10}}


class _Stream:
    def __init__(self, frame_bytes: bytes | None, ts: float) -> None:
        self._frame_bytes = frame_bytes
        self._ts = ts

    def get_last(self) -> tuple[bytes | None, float]:
        return self._frame_bytes, self._ts


class VisionSecondaryDetectionServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_secondary_detections_uses_recent_cache_first(self) -> None:
        state = SecondaryDetectionsState()
        state.last_payload = {"detections": [{"label": "chat"}], "status": {"state": "ok"}}
        state.last_refresh_ts = 10.0
        request_calls: list[str] = []
        deps = VisionSecondaryDetectionDeps(
            now=lambda: 10.5,
            request_secondary_stream=lambda: request_calls.append("call") or True,
            get_stream=lambda _input_url, _fps: (_ for _ in ()).throw(AssertionError("unused")),
            decode_frame=lambda _frame_bytes: (_ for _ in ()).throw(AssertionError("unused")),
            detect_secondary_frame=lambda _vision, _frame: (_ for _ in ()).throw(
                AssertionError("unused")
            ),
        )

        result = await collect_secondary_detections(
            arbitrator=_Arbitrator(),
            state=state,
            refresh_lock=asyncio.Lock(),
            stream_config=SecondaryStreamConfig(),
            vision=_Vision(),
            deps=deps,
        )

        self.assertEqual(result["source"], "secondary_cache")
        self.assertEqual(request_calls, [])

    async def test_collect_secondary_detections_holds_last_non_empty_on_arbitration_denied(
        self,
    ) -> None:
        state = SecondaryDetectionsState(non_empty_hold_ttl_s=4.0)
        state.last_non_empty_payload = {
            "detections": [{"label": "voiture"}],
            "status": {"state": "ok"},
        }
        state.last_non_empty_ts = 10.0
        deps = VisionSecondaryDetectionDeps(
            now=lambda: 12.0,
            request_secondary_stream=lambda: False,
            get_stream=lambda _input_url, _fps: None,
            decode_frame=lambda _frame_bytes: None,
            detect_secondary_frame=lambda _vision, _frame: None,
        )

        result = await collect_secondary_detections(
            arbitrator=_Arbitrator(),
            state=state,
            refresh_lock=asyncio.Lock(),
            stream_config=SecondaryStreamConfig(),
            vision=_Vision(),
            deps=deps,
        )

        self.assertEqual(result["source"], "secondary_hold_non_empty")
        self.assertEqual(
            result["status"]["state"],
            "hold_last_non_empty:arbitration_denied:secondary_stream",
        )

    async def test_collect_secondary_detections_refreshes_from_stream(self) -> None:
        state = SecondaryDetectionsState()
        vision = _Vision()
        deps = VisionSecondaryDetectionDeps(
            now=lambda: 20.0,
            request_secondary_stream=lambda: True,
            get_stream=lambda _input_url, _fps: _Stream(b"jpeg", 18.5),
            decode_frame=lambda _frame_bytes: "decoded-frame",
            detect_secondary_frame=lambda target_vision, frame: target_vision.detect_secondary_frame(
                frame
            ),
        )

        result = await collect_secondary_detections(
            arbitrator=_Arbitrator(),
            state=state,
            refresh_lock=asyncio.Lock(),
            stream_config=SecondaryStreamConfig(enabled=True, input_url="udp://stream", fps=15),
            vision=vision,
            deps=deps,
        )

        self.assertEqual(result["detections"][0]["label"], "personne")
        self.assertEqual(result["stream_ts"], 18.5)
        self.assertEqual(state.last_payload["stream_ts"], 18.5)
        self.assertEqual(vision.calls, ["decoded-frame"])


if __name__ == "__main__":
    unittest.main()
