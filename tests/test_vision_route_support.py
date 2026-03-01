import unittest
from types import SimpleNamespace

from core.vision_route_support import VisionRouteGuardError
from core.vision_route_support import enforce_npu_requirement
from core.vision_route_support import get_vision_tentacle
from core.vision_route_support import require_vision_capability
from core.vision_route_support import require_vision_tentacle


class VisionRouteSupportTests(unittest.TestCase):
    def test_get_vision_tentacle_returns_none_when_missing(self) -> None:
        orchestrator = SimpleNamespace(get_tentacle=lambda name: None)

        self.assertIsNone(get_vision_tentacle(orchestrator))

    def test_require_vision_tentacle_raises_when_missing(self) -> None:
        orchestrator = SimpleNamespace(get_tentacle=lambda name: None)

        with self.assertRaises(VisionRouteGuardError) as ctx:
            require_vision_tentacle(orchestrator)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, "vision tentacle not loaded")

    def test_require_vision_capability_checks_attribute(self) -> None:
        vision = SimpleNamespace()
        orchestrator = SimpleNamespace(get_tentacle=lambda name: vision)

        with self.assertRaises(VisionRouteGuardError) as ctx:
            require_vision_capability(
                orchestrator,
                "capture_once",
                unsupported_detail="capture not supported",
            )

        self.assertEqual(ctx.exception.status_code, 501)
        self.assertEqual(ctx.exception.detail, "capture not supported")

    def test_enforce_npu_requirement_raises_when_required_but_not_hailo(self) -> None:
        vision = SimpleNamespace(get_status=lambda: {"detector": "opencv-shape", "ready": True})
        orchestrator = SimpleNamespace(
            get_tentacle=lambda name: vision,
            config={"npu": {"required_for_vision": True}},
        )

        with self.assertRaises(VisionRouteGuardError) as ctx:
            enforce_npu_requirement(orchestrator, vision)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, "npu_required_for_vision:opencv-shape:ready")

    def test_enforce_npu_requirement_accepts_active_hailo(self) -> None:
        vision = SimpleNamespace(get_status=lambda: {"detector": "hailo", "ready": True})
        orchestrator = SimpleNamespace(
            get_tentacle=lambda name: vision,
            config={"npu": {"required_for_vision": True}},
        )

        enforce_npu_requirement(orchestrator, vision)


if __name__ == "__main__":
    unittest.main()
