import asyncio
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from core.config_schema import PicobotConfig
from core.picobot_client import metrics_from_picobot
from core.picobot_client import picobot_http_call
from core.picobot_client import route_from_picobot


class _FakeResponse:
    def __init__(
        self,
        *,
        is_success: bool,
        status_code: int,
        payload=None,
        text: str = "",
    ) -> None:
        self.is_success = is_success
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, response=None, exc: Exception | None = None) -> None:
        self._response = response
        self._exc = exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None):
        if self._exc is not None:
            raise self._exc
        return self._response

    async def request(self, method, url, json=None):
        if self._exc is not None:
            raise self._exc
        return self._response


class PicobotClientTests(unittest.TestCase):
    def test_metrics_from_picobot_tries_multiple_paths_until_success(self) -> None:
        picobot_config = PicobotConfig.from_mapping({"base_url": "http://192.168.1.50:5012"})
        responses = [
            _FakeClient(response=_FakeResponse(is_success=False, status_code=503)),
            _FakeClient(
                response=_FakeResponse(
                    is_success=True,
                    status_code=200,
                    payload={"metrics": {"queue": 1}},
                )
            ),
        ]

        with patch("core.picobot_client.httpx.AsyncClient", side_effect=responses):
            result = asyncio.run(
                metrics_from_picobot(
                    picobot_config=picobot_config,
                    timeout_s=1.0,
                    fallback_bases=(),
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "picobot")
        self.assertEqual(result["endpoint"], "http://192.168.1.50:5012/metrics")
        self.assertEqual(result["metrics"], {"queue": 1})

    def test_picobot_http_call_returns_last_error_after_failures(self) -> None:
        picobot_config = PicobotConfig.from_mapping({"base_url": "http://192.168.1.50:5012"})
        clients = [
            _FakeClient(exc=RuntimeError("boom")),
            _FakeClient(response=_FakeResponse(is_success=False, status_code=404)),
        ]

        with patch("core.picobot_client.httpx.AsyncClient", side_effect=clients):
            result = asyncio.run(
                picobot_http_call(
                    picobot_config=picobot_config,
                    method="GET",
                    paths=("/a", "/b"),
                    payload={},
                    timeout_s=1.0,
                    fallback_bases=(),
                )
            )

        self.assertFalse(result["ok"])
        self.assertIn("http 404 on http://192.168.1.50:5012/b", result["error"])

    def test_route_from_picobot_builds_context_payload(self) -> None:
        picobot_config = PicobotConfig.from_mapping({"base_url": "http://192.168.1.50:5012"})
        mocked = AsyncMock(return_value={"ok": True})

        with patch("core.picobot_client.picobot_http_call", mocked):
            asyncio.run(
                route_from_picobot(
                    picobot_config=picobot_config,
                    prompt="Bonjour",
                    task_type="chat",
                    payload={"boost": True},
                    timeout_s=1.5,
                    fallback_bases=(),
                )
            )

        kwargs = mocked.await_args.kwargs
        self.assertEqual(kwargs["method"], "POST")
        self.assertEqual(kwargs["paths"], ("/agent/route",))
        self.assertEqual(
            kwargs["payload"],
            {
                "prompt": "Bonjour",
                "task_type": "chat",
                "context": {"boost": True},
            },
        )


if __name__ == "__main__":
    unittest.main()
