import asyncio
import unittest
from types import SimpleNamespace

from core.ai_ask_and_speak_service import AskAndSpeakDeps
from core.ai_ask_and_speak_service import handle_ask_and_speak
from core.config_schema import OllamaConfig


class _Arbitrator:
    def __init__(self, granted: bool = True) -> None:
        self.granted = granted
        self.requests: list[str] = []

    def request_resource(self, resource: str) -> bool:
        self.requests.append(resource)
        return self.granted


class AIAskAndSpeakServiceTests(unittest.TestCase):
    def _deps(self, **overrides):
        async def _process_input(*args, **kwargs):
            return {
                "response": "Action en cours.",
                "task": True,
                "route": "picobot",
                "task_type": "music",
                "routing": {"execution_backend": "picobot"},
            }

        async def _deliver_dual_response(*args, **kwargs):
            return {"audio": True, "audio_status": "queued"}

        async def _generate_conversation_response(**kwargs):
            return {
                "response": "Bonjour",
                "task": False,
                "route": "local_ollama",
                "task_type": kwargs["task_type"],
                "routing": kwargs["backend_choice"],
            }

        base = dict(
            looks_like_web_query=lambda text: False,
            looks_like_task_request=lambda text, **kwargs: False,
            process_input=_process_input,
            prepare_chat_text=lambda text, **kwargs: str(text or "").strip(),
            runtime_qos_snapshot=lambda: {
                "mode": "NOMINAL",
                "llm_profile": "full",
                "audio_queue_size": 0,
                "audio_speaking": False,
            },
            resolve_expert_prompt=lambda prompt, config: (str(prompt).strip(), None, None, None),
            infer_task_type=lambda text, payload, **kwargs: "chat",
            choose_backend=lambda text, task_type, payload: {"execution_backend": "local_ollama"},
            normalize_text=lambda text: str(text or "").strip().lower(),
            looks_like_identity_query=lambda text: False,
            looks_like_local_status_query=lambda text: False,
            deliver_dual_response=_deliver_dual_response,
            parse_switch_action=lambda text: None,
            resolve_actuator_target=lambda text, devices: None,
            is_music_prompt=lambda text: False,
            generate_conversation_response=_generate_conversation_response,
        )
        base.update(overrides)
        return AskAndSpeakDeps(**base)

    def test_handle_ask_and_speak_routes_task_requests(self) -> None:
        orchestrator = SimpleNamespace(
            config={},
            get_tentacle=lambda name: None,
        )
        result = asyncio.run(
            handle_ask_and_speak(
                prompt="Lance la musique",
                payload={"is_voice": True},
                orchestrator=orchestrator,
                api_module=SimpleNamespace(asyncio=asyncio, _is_music_prompt=lambda text: False),
                arbitrator=_Arbitrator(),
                ollama_config=OllamaConfig(),
                deps=self._deps(
                    looks_like_task_request=lambda text, **kwargs: True,
                ),
            )
        )

        self.assertTrue(result["task"])
        self.assertEqual(result["route"], "picobot")
        self.assertEqual(result["response"], "Action en cours.")
        self.assertTrue(result["audio"])

    def test_handle_ask_and_speak_returns_stub_on_budget_timeout(self) -> None:
        async def _timeout_generation(**kwargs):
            raise asyncio.TimeoutError()

        arbitrator = _Arbitrator(granted=True)
        orchestrator = SimpleNamespace(
            config={},
            get_tentacle=lambda name: None,
        )
        result = asyncio.run(
            handle_ask_and_speak(
                prompt="Salut",
                payload={"is_voice": False},
                orchestrator=orchestrator,
                api_module=SimpleNamespace(asyncio=asyncio, _is_music_prompt=lambda text: False),
                arbitrator=arbitrator,
                ollama_config=OllamaConfig(ask_and_speak_budget_seconds=1.2),
                deps=self._deps(
                    generate_conversation_response=_timeout_generation,
                ),
            )
        )

        self.assertEqual(arbitrator.requests, ["llm_generation"])
        self.assertEqual(result["route"], "stub")
        self.assertEqual(result["response"], "Je suis en charge. Reessaie dans quelques secondes.")
        self.assertTrue(result["routing"]["fallback_active"])
        self.assertIn("ask_and_speak_budget_timeout", result["routing"]["fallback_reason"])
        self.assertTrue(result["audio"])

    def test_handle_ask_and_speak_short_circuits_identity_query(self) -> None:
        orchestrator = SimpleNamespace(
            config={},
            get_tentacle=lambda name: None,
        )
        result = asyncio.run(
            handle_ask_and_speak(
                prompt="Tu es quel modele ?",
                payload={"is_voice": False},
                orchestrator=orchestrator,
                api_module=SimpleNamespace(asyncio=asyncio, _is_music_prompt=lambda text: False),
                arbitrator=_Arbitrator(),
                ollama_config=OllamaConfig(
                    model="qwen-default",
                    ask_model="qwen-ask",
                ),
                deps=self._deps(
                    looks_like_identity_query=lambda text: True,
                    choose_backend=lambda text, task_type, payload: {
                        "execution_backend": "local_ollama",
                        "recommended_model": "qwen-id",
                    },
                ),
            )
        )

        self.assertEqual(result["route"], "local_info")
        self.assertEqual(result["response"], "Je suis Didier. Modele: qwen-id. Backend: local_ollama.")
        self.assertTrue(result["audio"])


if __name__ == "__main__":
    unittest.main()
