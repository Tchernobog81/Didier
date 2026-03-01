import unittest

from core.vision_npu_policy import is_hailo_vision_active
from core.vision_npu_policy import estimated_npu_utilization
from core.vision_npu_policy import npu_requirement_error
from core.vision_npu_policy import vision_npu_status


class VisionNPUStatePolicyTests(unittest.TestCase):
    def test_is_hailo_vision_active_requires_hailo_and_ready(self) -> None:
        self.assertTrue(is_hailo_vision_active({"detector": "hailo", "ready": True}))
        self.assertFalse(is_hailo_vision_active({"detector": "hailo", "ready": False}))
        self.assertFalse(is_hailo_vision_active({"detector": "opencv-shape", "ready": True}))

    def test_npu_requirement_error_is_only_raised_when_required_and_inactive(self) -> None:
        self.assertIsNone(
            npu_requirement_error(
                {"detector": "opencv-shape", "ready": True},
                required_for_vision=False,
            )
        )
        self.assertEqual(
            npu_requirement_error(
                {"detector": "opencv-shape", "ready": True},
                required_for_vision=True,
            ),
            "npu_required_for_vision:opencv-shape:ready",
        )
        self.assertIsNone(
            npu_requirement_error(
                {"detector": "hailo", "ready": True},
                required_for_vision=True,
            )
        )

    def test_vision_npu_status_exposes_target_and_reason(self) -> None:
        active = vision_npu_status(
            detector_name="hailo",
            detector_ready=True,
            required_for_vision=True,
        )
        blocked = vision_npu_status(
            detector_name="opencv-shape",
            detector_ready=True,
            required_for_vision=True,
        )
        cpu = vision_npu_status(
            detector_name="opencv-shape",
            detector_ready=True,
            required_for_vision=False,
        )

        self.assertEqual(active["execution_target"], "npu")
        self.assertEqual(active["reason"], "hailo_active")
        self.assertEqual(blocked["execution_target"], "blocked")
        self.assertEqual(blocked["reason"], "npu_required_but_inactive")
        self.assertEqual(cpu["execution_target"], "cpu")
        self.assertEqual(cpu["reason"], "fallback_or_cpu_mode")

    def test_estimated_npu_utilization_tracks_live_fps_when_driver_util_is_missing(self) -> None:
        self.assertEqual(
            estimated_npu_utilization(infer_fps=15.0, secondary_fps=1.0, reference_fps=20.0),
            80,
        )
        self.assertIsNone(
            estimated_npu_utilization(infer_fps=0.0, secondary_fps=0.0, reference_fps=20.0)
        )


if __name__ == "__main__":
    unittest.main()
