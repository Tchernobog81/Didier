import unittest

from core.system_camera_service import CameraControlConfig
from core.system_camera_service import camera_force_format_payload
from core.system_camera_service import camera_holders_payload
from core.system_camera_service import camera_reconnect_payload


class _Config:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = dict(values)

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class SystemCameraServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_camera_control_config_reads_runtime_values(self) -> None:
        config = CameraControlConfig.from_config(
            _Config(
                {
                    "vision.camera_device": "/dev/video2",
                    "vision.width": 1280,
                    "vision.height": 720,
                    "vision.fourcc": "MJPG",
                }
            )
        )

        self.assertEqual(config.camera_device, "/dev/video2")
        self.assertEqual(config.width, 1280)
        self.assertEqual(config.height, 720)
        self.assertEqual(config.fourcc, "MJPG")

    async def test_camera_holders_payload_uses_camera_device(self) -> None:
        calls: list[object] = []

        async def _holders(camera_device: object) -> dict[str, object]:
            calls.append(camera_device)
            return {"holders": ["ffmpeg"]}

        result = await camera_holders_payload(
            CameraControlConfig(camera_device="/dev/video1"),
            camera_holders_fn=_holders,
        )

        self.assertEqual(calls, ["/dev/video1"])
        self.assertEqual(result["holders"], ["ffmpeg"])

    async def test_camera_reconnect_payload_uses_camera_device(self) -> None:
        calls: list[object] = []

        async def _reconnect(camera_device: object) -> dict[str, object]:
            calls.append(camera_device)
            return {"ok": True}

        result = await camera_reconnect_payload(
            CameraControlConfig(camera_device="/dev/video0"),
            camera_reconnect_fn=_reconnect,
        )

        self.assertEqual(calls, ["/dev/video0"])
        self.assertTrue(result["ok"])

    async def test_camera_force_format_payload_forwards_full_format_tuple(self) -> None:
        calls: list[tuple[object, object, object, object]] = []

        async def _force(
            camera_device: object,
            width: object,
            height: object,
            fourcc: object,
        ) -> dict[str, object]:
            calls.append((camera_device, width, height, fourcc))
            return {"applied": True}

        result = await camera_force_format_payload(
            CameraControlConfig(
                camera_device="/dev/video3",
                width=640,
                height=480,
                fourcc="YUYV",
            ),
            camera_force_format_fn=_force,
        )

        self.assertEqual(calls, [("/dev/video3", 640, 480, "YUYV")])
        self.assertTrue(result["applied"])


if __name__ == "__main__":
    unittest.main()
