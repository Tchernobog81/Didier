import unittest

from core.system_device_status_service import DeviceStatusCollector
from core.system_device_status_service import DeviceStatusDeps


class _Config:
    def __init__(self, values: dict[str, object]) -> None:
        self._values = dict(values)

    def get(self, key: str, default=None):
        return self._values.get(key, default)


class _Vision:
    def __init__(self, last_frame_ts: float) -> None:
        self._last_frame_ts = last_frame_ts

    def get_status(self) -> dict[str, float]:
        return {"last_frame_ts": self._last_frame_ts}


class _Stream:
    def __init__(self, frame: bytes | None, ts: float) -> None:
        self._frame = frame
        self._ts = ts

    def get_last(self) -> tuple[bytes | None, float]:
        return self._frame, self._ts


class SystemDeviceStatusServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_collect_uses_vision_status_and_secondary_stream(self) -> None:
        check_camera_calls: list[tuple[int, object]] = []

        async def _check_camera(camera_index: int, camera_device: object) -> dict[str, object]:
            check_camera_calls.append((camera_index, camera_device))
            return {"source": "fallback"}

        orchestrator = type(
            "Orchestrator",
            (),
            {
                "config": _Config(
                    {
                        "vision.camera_index": 2,
                        "vision.camera_device": "/dev/video2",
                        "vision.remote_stream": {"enabled": True},
                        "bluetooth.sink_name": "bluez_sink.didier",
                        "tts.model_path": "model.onnx",
                        "tts.config_path": "tts.json",
                        "tts.voices_path": "voices/",
                        "npu.device": "/dev/hailo0",
                        "npu.pcie_address": "0001:01:00.0",
                        "ollama.model_profiles.ask": "qwen2.5:3b",
                        "ollama.model_profiles.coding": "qwen2.5-coder:7b",
                    }
                ),
                "get_tentacle": lambda self, name: _Vision(8.0) if name == "vision" else None,
            },
        )()

        async def _ok_payload(*_args) -> dict[str, object]:
            return {"ok": True}

        collector = DeviceStatusCollector(cache_ttl_s=5.0)
        deps = DeviceStatusDeps(
            get_orchestrator=lambda: orchestrator,
            now=lambda: 10.0,
            get_remote_stream=lambda: _Stream(b"frame", 9.0),
            check_camera=_check_camera,
            check_camera_usb=lambda _vendor, _product: _ok_payload(),
            check_camera_mic=lambda: _ok_payload(),
            check_soundboks_sink=lambda _sink: _ok_payload(),
            check_npu=lambda _device, _pcie: _ok_payload(),
            check_tts=lambda _model, _config, _voices: _ok_payload(),
            read_version=lambda: _ok_payload(),
        )

        result = await collector.collect(deps=deps)

        self.assertEqual(result["camera"]["source"], "vision")
        self.assertTrue(result["camera"]["opened"])
        self.assertTrue(result["camera_secondary"]["opened"])
        self.assertTrue(result["camera_secondary"]["frame"])
        self.assertEqual(result["models"]["didier"], "qwen2.5:3b")
        self.assertEqual(result["models"]["coding"], "qwen2.5-coder:7b")
        self.assertEqual(check_camera_calls, [])

    async def test_collect_falls_back_to_check_camera_and_uses_cache(self) -> None:
        now_holder = {"value": 20.0}
        camera_calls: list[tuple[int, object]] = []
        orchestrator_calls = {"count": 0}

        async def _check_camera(camera_index: int, camera_device: object) -> dict[str, object]:
            camera_calls.append((camera_index, camera_device))
            return {"device": f"index:{camera_index}", "source": "fallback"}

        def _get_orchestrator():
            orchestrator_calls["count"] += 1
            return type(
                "Orchestrator",
                (),
                {
                    "config": _Config(
                        {
                            "vision.camera_index": 1,
                            "vision.remote_stream": {"enabled": False},
                            "ollama.model": "qwen2.5:1.5b",
                        }
                    ),
                    "get_tentacle": lambda self, _name: None,
                },
            )()

        async def _ok_payload(*_args) -> dict[str, object]:
            return {"ok": True}

        collector = DeviceStatusCollector(cache_ttl_s=5.0)
        deps = DeviceStatusDeps(
            get_orchestrator=_get_orchestrator,
            now=lambda: now_holder["value"],
            get_remote_stream=lambda: None,
            check_camera=_check_camera,
            check_camera_usb=lambda _vendor, _product: _ok_payload(),
            check_camera_mic=lambda: _ok_payload(),
            check_soundboks_sink=lambda _sink: _ok_payload(),
            check_npu=lambda _device, _pcie: _ok_payload(),
            check_tts=lambda _model, _config, _voices: _ok_payload(),
            read_version=lambda: _ok_payload(),
        )

        first = await collector.collect(deps=deps)
        now_holder["value"] = 22.0
        second = await collector.collect(deps=deps)

        self.assertEqual(first["camera"]["source"], "fallback")
        self.assertFalse(first["camera_secondary"]["enabled"])
        self.assertEqual(second["camera"]["source"], "fallback")
        self.assertEqual(camera_calls, [(1, None)])
        self.assertEqual(orchestrator_calls["count"], 1)

    async def test_invalidate_forces_recompute(self) -> None:
        calls = {"count": 0}

        async def _check_camera(camera_index: int, camera_device: object) -> dict[str, object]:
            calls["count"] += 1
            return {"device": f"index:{camera_index}", "source": "fallback"}

        orchestrator = type(
            "Orchestrator",
            (),
            {
                "config": _Config({"vision.camera_index": 0}),
                "get_tentacle": lambda self, _name: None,
            },
        )()

        async def _ok_payload(*_args) -> dict[str, object]:
            return {"ok": True}

        collector = DeviceStatusCollector(cache_ttl_s=60.0)
        deps = DeviceStatusDeps(
            get_orchestrator=lambda: orchestrator,
            now=lambda: 30.0,
            get_remote_stream=lambda: None,
            check_camera=_check_camera,
            check_camera_usb=lambda _vendor, _product: _ok_payload(),
            check_camera_mic=lambda: _ok_payload(),
            check_soundboks_sink=lambda _sink: _ok_payload(),
            check_npu=lambda _device, _pcie: _ok_payload(),
            check_tts=lambda _model, _config, _voices: _ok_payload(),
            read_version=lambda: _ok_payload(),
        )

        await collector.collect(deps=deps)
        collector.invalidate()
        await collector.collect(deps=deps)

        self.assertEqual(calls["count"], 2)


if __name__ == "__main__":
    unittest.main()
