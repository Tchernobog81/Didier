import asyncio
import unittest

from core.vision_describe_service import VisionDescribeDeps
from core.vision_describe_service import VisionDescribeServiceError
from core.vision_describe_service import describe_latest_frame


class VisionDescribeServiceTests(unittest.TestCase):
    def _deps(self, **overrides):
        async def _capture_once():
            return "/tmp/capture.jpg"

        async def _post_generate(base_url, payload_data, timeout_s):
            return {"response": "Image utile"}

        base = dict(
            get_latest_jpeg=lambda: b"jpeg",
            capture_once=_capture_once,
            read_bytes=lambda path: b"captured",
            post_generate=_post_generate,
        )
        base.update(overrides)
        return VisionDescribeDeps(**base)

    def test_describe_latest_frame_prefers_cached_jpeg(self) -> None:
        calls: list[dict[str, object]] = []

        async def _post_generate(base_url, payload_data, timeout_s):
            calls.append(
                {
                    "base_url": base_url,
                    "payload": dict(payload_data),
                    "timeout_s": timeout_s,
                }
            )
            return {"response": "Vue nette"}

        result = asyncio.run(
            describe_latest_frame(
                prompt="Décris",
                model="moondream",
                num_predict=120,
                base_url="http://localhost:11434",
                keep_alive="0",
                timeout_s=2.0,
                deps=self._deps(post_generate=_post_generate),
            )
        )

        self.assertEqual(result["response"], "Vue nette")
        self.assertEqual(result["model"], "moondream")
        self.assertEqual(calls[0]["base_url"], "http://localhost:11434")
        self.assertEqual(calls[0]["payload"]["model"], "moondream")
        self.assertEqual(calls[0]["payload"]["options"]["num_predict"], 120)
        self.assertEqual(calls[0]["payload"]["keep_alive"], "0")

    def test_describe_latest_frame_falls_back_to_capture(self) -> None:
        result = asyncio.run(
            describe_latest_frame(
                prompt="Décris",
                model="moondream",
                num_predict=80,
                base_url="http://localhost:11434",
                keep_alive=None,
                timeout_s=2.0,
                deps=self._deps(get_latest_jpeg=lambda: None),
            )
        )

        self.assertEqual(result["response"], "Image utile")

    def test_describe_latest_frame_raises_when_no_image_is_available(self) -> None:
        with self.assertRaises(VisionDescribeServiceError):
            asyncio.run(
                describe_latest_frame(
                    prompt="Décris",
                    model="moondream",
                    num_predict=80,
                    base_url="http://localhost:11434",
                    keep_alive=None,
                    timeout_s=2.0,
                    deps=self._deps(
                        get_latest_jpeg=lambda: None,
                        capture_once=None,
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
