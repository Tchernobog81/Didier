import unittest

from core.vision_stream_service import PrimaryStreamConfig
from core.vision_stream_service import SecondaryStreamConfig
from core.vision_stream_service import build_primary_camera_plan
from core.vision_stream_service import build_secondary_stream_plan
from core.vision_stream_service import evaluate_primary_stream
from core.vision_stream_service import stream_emit_interval


class VisionStreamServiceTests(unittest.TestCase):
    def test_evaluate_primary_stream_uses_live_stream_when_recent(self) -> None:
        decision = evaluate_primary_stream(
            config=PrimaryStreamConfig(
                enable_live=True,
                primary_fallback_secondary=True,
                primary_stale_fallback_seconds=2.5,
            ),
            has_vision=True,
            has_live_jpeg=True,
            cached_jpeg=b"jpeg",
            last_frame_ts=10.0,
            now=11.0,
        )

        self.assertTrue(decision.use_live_stream)
        self.assertFalse(decision.should_try_secondary_fallback)
        self.assertFalse(decision.primary_stream_stale)

    def test_evaluate_primary_stream_flags_stale_and_secondary_fallback(self) -> None:
        decision = evaluate_primary_stream(
            config=PrimaryStreamConfig(
                enable_live=True,
                primary_fallback_secondary=True,
                primary_stale_fallback_seconds=1.5,
            ),
            has_vision=True,
            has_live_jpeg=True,
            cached_jpeg=b"jpeg",
            last_frame_ts=10.0,
            now=12.0,
        )

        self.assertFalse(decision.use_live_stream)
        self.assertTrue(decision.should_try_secondary_fallback)
        self.assertTrue(decision.primary_stream_stale)

    def test_build_secondary_stream_plan_requires_enabled_url_and_ffmpeg(self) -> None:
        plan, error = build_secondary_stream_plan(
            config=SecondaryStreamConfig(enabled=False, input_url="udp://x", fps=15),
            target_fps=15,
            ffmpeg_available=True,
        )
        self.assertIsNone(plan)
        self.assertEqual(error, "secondary stream disabled")

        plan, error = build_secondary_stream_plan(
            config=SecondaryStreamConfig(enabled=True, input_url="", fps=15),
            target_fps=15,
            ffmpeg_available=True,
        )
        self.assertIsNone(plan)
        self.assertEqual(error, "input_url required")

        plan, error = build_secondary_stream_plan(
            config=SecondaryStreamConfig(enabled=True, input_url="udp://x", fps=15),
            target_fps=18,
            ffmpeg_available=True,
        )
        self.assertIsNotNone(plan)
        self.assertIsNone(error)
        self.assertEqual(plan.fps, 15)

    def test_build_primary_camera_plan_keeps_effective_capture_settings(self) -> None:
        plan = build_primary_camera_plan(
            config=PrimaryStreamConfig(
                api_local_capture_enabled=False,
                camera_index=2,
                camera_device="/dev/video2",
                width=800,
                height=600,
                fps=15,
                fourcc="MJPG",
                kill_on_open=True,
            ),
            target_fps=12,
        )

        self.assertFalse(plan.api_local_capture_enabled)
        self.assertEqual(plan.camera_index, 2)
        self.assertEqual(plan.camera_device, "/dev/video2")
        self.assertEqual(plan.width, 800)
        self.assertEqual(plan.height, 600)
        self.assertEqual(plan.fps, 12)
        self.assertEqual(plan.fourcc, "MJPG")
        self.assertTrue(plan.kill_on_open)

    def test_stream_emit_interval_can_follow_or_ignore_target_fps(self) -> None:
        self.assertAlmostEqual(
            stream_emit_interval(
                configured_fps=15,
                target_fps=10,
                follow_target=True,
            ),
            0.1,
            places=3,
        )
        self.assertAlmostEqual(
            stream_emit_interval(
                configured_fps=15,
                target_fps=10,
                follow_target=False,
            ),
            1.0 / 15.0,
            places=3,
        )


if __name__ == "__main__":
    unittest.main()
