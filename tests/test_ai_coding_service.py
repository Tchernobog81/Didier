import asyncio
import unittest
from unittest.mock import patch

from core.ai_coding_service import CodingGenerationDeps
from core.ai_coding_service import CodingServiceError
from core.ai_coding_service import generate_coding_response
from core.config_schema import CodingConfig
from core.config_schema import OllamaConfig


class _FakeResponse:
    def __init__(self, payload: dict[str, str]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, str]:
        return dict(self._payload)


class _FakeAsyncClient:
    last_timeout = None
    last_url = ""
    last_json = None

    def __init__(self, *, timeout) -> None:
        type(self).last_timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, json: dict) -> _FakeResponse:
        type(self).last_url = url
        type(self).last_json = dict(json)
        return _FakeResponse({"response": "code ok"})


class AICodingServiceTests(unittest.TestCase):
    def _deps(self, **overrides):
        async def _list_models(base_url):
            return ["qwen2.5-coder:1.5b"]

        def _pick_model(available_models, candidates):
            for item in candidates:
                if item:
                    return item
            return available_models[0] if available_models else None

        base = dict(
            list_ollama_models=_list_models,
            pick_model=_pick_model,
            request_timeout=lambda: 4.0,
        )
        base.update(overrides)
        return CodingGenerationDeps(**base)

    def test_generate_coding_response_uses_typed_config(self) -> None:
        with patch("core.ai_coding_service.httpx.AsyncClient", _FakeAsyncClient):
            result = asyncio.run(
                generate_coding_response(
                    prompt="Ecris une fonction",
                    ollama_config=OllamaConfig(
                        base_url="http://localhost:11434",
                        keep_alive="15m",
                    ),
                    coding_config=CodingConfig(
                        model="coder-x",
                        num_predict=256,
                        temperature=0.1,
                        system_prompt="Tu es un assistant code.",
                    ),
                    deps=self._deps(),
                )
            )

        self.assertEqual(result["response"], "code ok")
        self.assertEqual(_FakeAsyncClient.last_timeout, 4.0)
        self.assertEqual(_FakeAsyncClient.last_url, "http://localhost:11434/api/generate")
        self.assertEqual(_FakeAsyncClient.last_json["model"], "coder-x")
        self.assertEqual(_FakeAsyncClient.last_json["options"]["num_predict"], 256)
        self.assertEqual(_FakeAsyncClient.last_json["options"]["temperature"], 0.1)
        self.assertEqual(_FakeAsyncClient.last_json["keep_alive"], "15m")
        self.assertIn("Tu es un assistant code.", _FakeAsyncClient.last_json["prompt"])

    def test_generate_coding_response_raises_when_no_model_is_available(self) -> None:
        with self.assertRaises(CodingServiceError):
            asyncio.run(
                generate_coding_response(
                    prompt="Ecris une fonction",
                    ollama_config=OllamaConfig(model=""),
                    coding_config=CodingConfig(model=""),
                    deps=self._deps(
                        list_ollama_models=lambda base_url: asyncio.sleep(0, result=[]),
                        pick_model=lambda available_models, candidates: None,
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
