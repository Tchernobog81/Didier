import asyncio
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from core.brain_client import generate_from_brain


class _FakeIPCResponse:
    def __init__(self, *, is_success: bool, status_code: int, payload=None) -> None:
        self.is_success = is_success
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class BrainClientTests(unittest.TestCase):
    def test_generate_from_brain_returns_normalized_success_payload(self) -> None:
        mocked = AsyncMock(
            return_value=_FakeIPCResponse(
                is_success=True,
                status_code=200,
                payload={"response": "Bonjour", "tokens": 12},
            )
        )

        with patch("core.brain_client.ipc_request", mocked):
            result = asyncio.run(
                generate_from_brain(
                    prompt="Salut",
                    task_type="react_task",
                    timeout_s=1.2,
                )
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "brain_worker")
        self.assertEqual(result["endpoint"], "unix://brain/generate")
        self.assertEqual(result["response"], "Bonjour")
        self.assertEqual(result["data"]["tokens"], 12)
        kwargs = mocked.await_args.kwargs
        self.assertEqual(kwargs["service"], "brain")
        self.assertEqual(kwargs["payload"]["prompt"], "Salut")
        self.assertEqual(kwargs["payload"]["task_type"], "react_task")
        self.assertEqual(kwargs["timeout"], 1.2)

    def test_generate_from_brain_handles_ipc_failure(self) -> None:
        mocked = AsyncMock(side_effect=RuntimeError("down"))

        with patch("core.brain_client.ipc_request", mocked):
            result = asyncio.run(
                generate_from_brain(
                    prompt="Salut",
                    timeout_s=0.5,
                )
            )

        self.assertFalse(result["ok"])
        self.assertIn("brain relay exception: down", result["error"])

    def test_generate_from_brain_handles_http_error(self) -> None:
        mocked = AsyncMock(
            return_value=_FakeIPCResponse(
                is_success=False,
                status_code=503,
            )
        )

        with patch("core.brain_client.ipc_request", mocked):
            result = asyncio.run(
                generate_from_brain(
                    prompt="Salut",
                    timeout_s=0.5,
                )
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "brain relay http 503")


if __name__ == "__main__":
    unittest.main()
