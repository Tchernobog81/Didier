import asyncio
import unittest
from types import SimpleNamespace

from core.ai_conversation_service import ConversationGenerationDeps
from core.ai_conversation_service import ConversationServiceError
from core.ai_conversation_service import generate_conversation_response
from core.config_schema import OllamaConfig
from core.config_schema import PicobotConfig
from core.config_schema import RoutingConfig


class AIConversationServiceTests(unittest.TestCase):
    def _api_module(self):
        updates: list[dict] = []

        def _update_status(**kwargs):
            updates.append(dict(kwargs))

        api_module = SimpleNamespace(
            update_status=_update_status,
            time=SimpleNamespace(time=lambda: 123.0),
        )
        return api_module, updates

    def _deps(self, **overrides):
        async def _noop_pair(*args, **kwargs):
            return None, None

        async def _resolve_base(*args, **kwargs):
            return "http://localhost:11434", dict(kwargs.get("backend_choice", {}) or {}), []

        async def _list_models(base_url):
            return ["qwen2.5:1.5b"]

        def _pick_model(available_models, candidates):
            for item in candidates:
                if item:
                    return item
            return available_models[0] if available_models else None

        base = dict(
            runtime_qos_snapshot=lambda: {"mode": "NOMINAL", "llm_profile": "full"},
            flag_enabled=lambda value: bool(value),
            try_gemini_boost_chat=_noop_pair,
            try_pixel_openai_chat=_noop_pair,
            resolve_ollama_base_for_backend=_resolve_base,
            list_ollama_models=_list_models,
            pick_model=_pick_model,
            finalize_model_response=lambda text: str(text or "").strip(),
            is_listening_only_response=lambda text: False,
            llm_http_timeout=lambda seconds: float(seconds),
            http_error_brief=lambda exc: type(exc).__name__,
            resolve_gemini_boost_config=lambda picobot_config: {
                "enabled": True,
                "model": "gemini-test",
                "timeout_s": 3.2,
                "max_tokens": 220,
            },
        )
        base.update(overrides)
        return ConversationGenerationDeps(**base)

    def test_generate_conversation_response_returns_gemini_boost_when_available(self) -> None:
        async def _gemini_success(*args, **kwargs):
            return "Bonjour", None

        api_module, updates = self._api_module()
        result = asyncio.run(
            generate_conversation_response(
                clean_prompt="Salut",
                task_type="chat",
                expert_model=None,
                expert_system=None,
                backend_choice={"execution_backend": "local_ollama"},
                payload={"boost": True},
                orchestrator=object(),
                api_module=api_module,
                ollama_config=OllamaConfig(),
                picobot_config=PicobotConfig.from_mapping({"llm_model": "pixel-model"}),
                routing_config=RoutingConfig(),
                deps=self._deps(try_gemini_boost_chat=_gemini_success),
            )
        )

        self.assertEqual(result["route"], "gemini_boost")
        self.assertEqual(result["model"], "gemini-test")
        self.assertEqual(result["response"], "Bonjour")
        self.assertTrue(result["routing"]["boost_active"])
        self.assertEqual(updates[-1]["state"], "IDLE")

    def test_generate_conversation_response_raises_when_no_model_is_available(self) -> None:
        async def _resolve_base(*args, **kwargs):
            return "http://localhost:11434", dict(kwargs.get("backend_choice", {}) or {}), []

        api_module, _updates = self._api_module()

        with self.assertRaises(ConversationServiceError):
            asyncio.run(
                generate_conversation_response(
                    clean_prompt="Salut",
                    task_type="chat",
                    expert_model=None,
                    expert_system=None,
                    backend_choice={"execution_backend": "local_ollama"},
                    payload={},
                    orchestrator=object(),
                    api_module=api_module,
                    ollama_config=OllamaConfig(),
                    picobot_config=PicobotConfig(),
                    routing_config=RoutingConfig(),
                    deps=self._deps(
                        resolve_ollama_base_for_backend=_resolve_base,
                        list_ollama_models=lambda base_url: asyncio.sleep(0, result=[]),
                        pick_model=lambda available_models, candidates: None,
                    ),
                )
            )


if __name__ == "__main__":
    unittest.main()
