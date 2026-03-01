import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core.ai_config import chat_cfg
from core.ai_config import coding_cfg
from core.ai_config import ollama_cfg
from core.ai_config import picobot_cfg
from core.ai_config import prepare_chat_text
from core.ai_config import prepare_tts_text
from core.ai_config import routing_cfg
from core.ai_config import tts_cfg
from core.config import DidierConfig
from core.config_loader import load_runtime_config
from core.text_compaction import text_stats


class AIConfigAccessTests(unittest.TestCase):
    def _write_config(self, payload: dict) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _loaded_orchestrator(self, payload: dict) -> SimpleNamespace:
        path = self._write_config(payload)
        loaded = load_runtime_config(path=path, env={})
        return SimpleNamespace(
            loaded_config=loaded,
            config=loaded.to_legacy(),
        )

    def test_ai_helpers_read_typed_config_from_loaded_config(self) -> None:
        orchestrator = self._loaded_orchestrator(
            {
                "chat": {"response_max_chars": 88},
                "tts": {"voice": "custom_voice", "response_max_chars": 66},
                "ollama": {
                    "model_profiles": {
                        "ask": "qwen-ask",
                        "coding": "qwen-code",
                    },
                    "timeout_seconds": 9.5,
                    "ask_and_speak_budget_seconds": 2.4,
                },
                "coding": {
                    "num_predict": 320,
                    "temperature": 0.1,
                },
                "picobot": {
                    "api_url": "http://192.168.1.47:5010",
                    "react_timeout_s": 6.2,
                },
                "routing": {
                    "pixel_openai": {
                        "max_tokens": 144,
                    }
                },
            }
        )

        self.assertEqual(chat_cfg(orchestrator).response_max_chars, 88)
        self.assertEqual(tts_cfg(orchestrator).voice, "custom_voice")
        self.assertEqual(tts_cfg(orchestrator).response_max_chars, 66)
        self.assertEqual(ollama_cfg(orchestrator).ask_model, "qwen-ask")
        self.assertEqual(ollama_cfg(orchestrator).coding_model, "qwen-code")
        self.assertEqual(ollama_cfg(orchestrator).timeout_seconds, 9.5)
        self.assertEqual(ollama_cfg(orchestrator).ask_and_speak_budget_seconds, 2.4)
        self.assertEqual(coding_cfg(orchestrator).num_predict, 320)
        self.assertEqual(coding_cfg(orchestrator).temperature, 0.1)
        self.assertEqual(picobot_cfg(orchestrator).base_url, "http://192.168.1.47:5010")
        self.assertEqual(picobot_cfg(orchestrator).react_timeout_s, 6.2)
        self.assertEqual(routing_cfg(orchestrator).pixel_openai_max_tokens, 144)

    def test_ai_helpers_remain_compatible_with_legacy_config_only(self) -> None:
        payload = {
            "chat": {"response_max_chars": 92},
            "tts": {"response_max_chars": 72},
            "ollama": {"model": "legacy-model"},
        }
        orchestrator = SimpleNamespace(
            config=DidierConfig.from_mapping(payload),
        )

        self.assertEqual(chat_cfg(orchestrator).response_max_chars, 92)
        self.assertEqual(tts_cfg(orchestrator).response_max_chars, 72)
        self.assertEqual(ollama_cfg(orchestrator).model, "legacy-model")

    def test_prepare_chat_text_uses_configured_limits(self) -> None:
        orchestrator = self._loaded_orchestrator(
            {
                "chat": {
                    "response_max_sentences": 1,
                    "response_max_chars": 80,
                }
            }
        )

        text = (
            "Premiere phrase tres longue pour tester la compaction. "
            "Deuxieme phrase a supprimer. Troisieme phrase aussi."
        )
        compacted = prepare_chat_text(text, orchestrator=orchestrator)
        stats = text_stats(compacted)

        self.assertLessEqual(len(compacted), 80)
        self.assertLessEqual(stats["sentences"], 1)

    def test_prepare_tts_text_uses_configured_limits(self) -> None:
        orchestrator = self._loaded_orchestrator(
            {
                "tts": {
                    "response_max_sentences": 1,
                    "response_max_chars": 60,
                }
            }
        )

        text = (
            "Voici une phrase longue avec un lien https://example.com a retirer. "
            "Cette deuxieme phrase doit disparaitre."
        )
        compacted = prepare_tts_text(text, orchestrator=orchestrator)
        stats = text_stats(compacted)

        self.assertLessEqual(len(compacted), 60)
        self.assertLessEqual(stats["sentences"], 1)
        self.assertNotIn("http", compacted.lower())


if __name__ == "__main__":
    unittest.main()
