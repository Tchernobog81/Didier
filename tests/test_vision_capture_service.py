import unittest

from core.vision_capture_service import CaptureSourceConfig
from core.vision_capture_service import build_gstreamer_pipeline
from core.vision_capture_service import can_use_v4l2_fallback
from core.vision_capture_service import iter_capture_attempts
from core.vision_capture_service import resolve_capture_source


class VisionCaptureServiceTests(unittest.TestCase):
    def test_resolve_capture_source_prefers_explicit_camera_source(self) -> None:
        config = CaptureSourceConfig(
            camera_index=0,
            camera_device="/dev/video0",
            camera_source="rtsp://surface/live",
        )

        self.assertEqual(resolve_capture_source(config), "rtsp://surface/live")
        self.assertFalse(can_use_v4l2_fallback(config))

    def test_build_gstreamer_pipeline_for_local_usb_camera(self) -> None:
        config = CaptureSourceConfig(
            camera_index=0,
            camera_device="/dev/video0",
            width=640,
            height=480,
            fps=60,
            fourcc="YUYV",
        )

        pipeline = build_gstreamer_pipeline(config)

        assert pipeline is not None
        self.assertIn("v4l2src device=/dev/video0", pipeline)
        self.assertIn("framerate=60/1", pipeline)
        self.assertIn("format=YUY2", pipeline)

    def test_iter_capture_attempts_uses_single_plain_attempt_for_network_stream(self) -> None:
        config = CaptureSourceConfig(camera_source="rtsp://surface/live")

        attempts = list(
            iter_capture_attempts(
                config,
                gstreamer_pipeline=None,
                cap_gstreamer=1800,
                cap_v4l2=200,
            )
        )

        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].backend_name, "opencv")
        self.assertEqual(attempts[0].source, "rtsp://surface/live")


if __name__ == "__main__":
    unittest.main()
