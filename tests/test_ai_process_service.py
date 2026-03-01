import asyncio
import unittest
from types import SimpleNamespace

from core.ai_process_service import ProcessInputDeps
from core.ai_process_service import process_input


class AIProcessServiceTests(unittest.TestCase):
    def _deps(self, **overrides):
        async def _vision_see_user(timeout_s):
            return {"seen": True, "timeout_s": timeout_s}

        async def _relay_picobot_react(**kwargs):
            return {"ok": True, "reply": "Action en cours."}

        async def _generate_conversation_response(**kwargs):
            return {
                "response": "Bonjour",
                "task": False,
                "route": "local_ollama",
                "task_type": kwargs["task_type"],
                "routing": kwargs["backend_choice"],
            }

        base = dict(
            resolve_expert_prompt=lambda prompt, config: (str(prompt).strip(), None, None, None),
            vision_see_user=_vision_see_user,
            vision_glance_text=lambda payload: "Vue OK." if payload else "",
            looks_like_web_query=lambda text: False,
            looks_like_task_request=lambda text, **kwargs: False,
            infer_task_type=lambda text, payload, **kwargs: "chat",
            choose_backend=lambda text, task_type, payload: {"execution_backend": "local_ollama"},
            relay_picobot_react=_relay_picobot_react,
            extract_agent_reply=lambda result: str((result or {}).get("reply", "")).strip(),
            build_task_apology=lambda error_msg: f"Desole. {error_msg}".strip(),
            prepend_glance=lambda response, glance: (
                f"{glance} {response}".strip() if glance else str(response or "").strip()
            ),
            generate_conversation_response=_generate_conversation_response,
        )
        base.update(overrides)
        return ProcessInputDeps(**base)

    def test_process_input_routes_task_requests_to_picobot(self) -> None:
        result = asyncio.run(
            process_input(
                prompt="Lance la musique",
                is_voice=True,
                payload={},
                image_bytes=None,
                orchestrator=SimpleNamespace(config={}),
                api_module=SimpleNamespace(),
                deps=self._deps(
                    looks_like_task_request=lambda text, **kwargs: True,
                    infer_task_type=lambda text, payload, **kwargs: "music",
                    choose_backend=lambda text, task_type, payload: {
                        "execution_backend": "picobot",
                        "preferred_backend": "picobot",
                    },
                ),
            )
        )

        self.assertTrue(result["task"])
        self.assertEqual(result["route"], "picobot")
        self.assertEqual(result["task_type"], "music")
        self.assertEqual(result["response"], "Vue OK. Action en cours.")
        self.assertEqual(result["source"], "process_input")
        self.assertTrue(result["vision"]["seen"])

    def test_process_input_keeps_conversation_flow_in_service(self) -> None:
        captured: dict[str, object] = {}

        async def _generate_conversation_response(**kwargs):
            captured["task_type"] = kwargs["task_type"]
            captured["prompt"] = kwargs["clean_prompt"]
            return {
                "response": "Bonjour",
                "task": False,
                "route": "local_ollama",
                "task_type": kwargs["task_type"],
                "routing": kwargs["backend_choice"],
            }

        result = asyncio.run(
            process_input(
                prompt="Salut",
                is_voice=False,
                payload={},
                image_bytes=None,
                orchestrator=SimpleNamespace(config={}),
                api_module=SimpleNamespace(),
                deps=self._deps(
                    generate_conversation_response=_generate_conversation_response,
                    infer_task_type=lambda text, payload, **kwargs: "chat",
                ),
            )
        )

        self.assertFalse(result["task"])
        self.assertEqual(result["route"], "local_ollama")
        self.assertEqual(result["response"], "Vue OK. Bonjour")
        self.assertEqual(result["source"], "process_input")
        self.assertEqual(captured["task_type"], "chat")
        self.assertEqual(captured["prompt"], "Salut")


if __name__ == "__main__":
    unittest.main()
