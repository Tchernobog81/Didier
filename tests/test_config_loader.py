import json
import tempfile
import unittest
from pathlib import Path

from core.config import DidierConfig
from core.config_access import chat_settings
from core.config_access import coding_settings
from core.config_access import effective_config_dict
from core.config_access import legacy_config
from core.config_access import npu_settings
from core.config_access import ollama_settings
from core.config_access import picobot_settings
from core.config_access import routing_settings
from core.config_access import to_runtime_config
from core.config_access import tts_settings
from core.config_access import vision_settings
from core.config_loader import load_runtime_config
from core.config_schema import DidierRuntimeConfig


class ConfigLoaderTests(unittest.TestCase):
    def _write_config(self, payload: dict) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_load_runtime_config_merges_defaults_and_file(self) -> None:
        path = self._write_config(
            {
                "chat": {
                    "response_max_chars": 180,
                },
                "vision": {
                    "remote_stream": {
                        "fps": 22,
                    }
                },
            }
        )

        loaded = load_runtime_config(path=path, env={})

        self.assertEqual(loaded.runtime.chat.response_max_sentences, 2)
        self.assertEqual(loaded.runtime.chat.response_max_chars, 180)
        self.assertEqual(loaded.runtime.tts.response_max_chars, 110)
        self.assertEqual(loaded.runtime.vision.remote_stream_fps, 22)
        self.assertEqual(loaded.get("vision.remote_stream.fps"), 22)
        self.assertFalse(loaded.applied_overrides)
        self.assertFalse(loaded.warnings)

    def test_env_overrides_apply_on_top_of_file_config(self) -> None:
        path = self._write_config(
            {
                "chat": {
                    "response_max_chars": 160,
                },
                "ollama": {
                    "model_profiles": {
                        "ask": "baseline",
                    }
                },
            }
        )

        loaded = load_runtime_config(
            path=path,
            env={
                "DIDIER_NPU_REQUIRED_FOR_VISION": "true",
                "DIDIER_CHAT_RESPONSE_MAX_CHARS": "120",
                "DIDIER_OLLAMA_ASK_MODEL": "qwen2.5:3b",
                "DIDIER_VISION_PRIMARY_FALLBACK_SECONDARY": "false",
            },
        )

        self.assertTrue(loaded.runtime.npu.required_for_vision)
        self.assertEqual(loaded.runtime.chat.response_max_chars, 120)
        self.assertEqual(loaded.runtime.ollama.ask_model, "qwen2.5:3b")
        self.assertFalse(loaded.runtime.vision.primary_fallback_secondary)
        self.assertEqual(
            loaded.applied_overrides,
            (
                "DIDIER_NPU_REQUIRED_FOR_VISION",
                "DIDIER_OLLAMA_ASK_MODEL",
                "DIDIER_CHAT_RESPONSE_MAX_CHARS",
                "DIDIER_VISION_PRIMARY_FALLBACK_SECONDARY",
            ),
        )

    def test_unknown_root_sections_generate_warnings(self) -> None:
        path = self._write_config(
            {
                "chat": {
                    "response_max_chars": 175,
                },
                "unknown_feature": {
                    "enabled": True,
                },
            }
        )

        loaded = load_runtime_config(path=path, env={})

        self.assertIn("Unknown top-level config section: unknown_feature", loaded.warnings)

    def test_access_helpers_support_mapping_legacy_and_loaded(self) -> None:
        payload = {
            "npu": {
                "required_for_vision": True,
            },
            "chat": {
                "response_max_chars": 190,
            },
            "tts": {
                "voice": "custom",
            },
            "coding": {
                "num_predict": 288,
            },
            "ollama": {
                "model_profiles": {
                    "coding": "coder-x",
                }
            },
            "vision": {
                "primary_fallback_secondary": False,
            },
            "picobot": {
                "api_url": "http://192.168.1.47:5010",
                "brain_fallback_enabled": True,
            },
            "routing": {
                "pixel_ollama": {
                    "health_timeout_s": 1.7,
                }
            },
        }
        path = self._write_config(payload)
        loaded = load_runtime_config(path=path, env={})
        legacy = DidierConfig.from_mapping(payload, source_path=path)

        runtime_from_mapping = to_runtime_config(payload)
        self.assertIsInstance(runtime_from_mapping, DidierRuntimeConfig)
        self.assertTrue(npu_settings(payload).required_for_vision)
        self.assertEqual(chat_settings(payload).response_max_chars, 190)
        self.assertEqual(tts_settings(legacy).voice, "custom")
        self.assertEqual(coding_settings(loaded).num_predict, 288)
        self.assertEqual(ollama_settings(loaded).coding_model, "coder-x")
        self.assertFalse(vision_settings(loaded).primary_fallback_secondary)
        self.assertEqual(picobot_settings(loaded).base_url, "http://192.168.1.47:5010")
        self.assertTrue(picobot_settings(loaded).brain_fallback_enabled)
        self.assertEqual(routing_settings(loaded).pixel_ollama_health_timeout_s, 1.7)

        legacy_from_runtime = legacy_config(runtime_from_mapping)
        self.assertEqual(legacy_from_runtime.get("chat.response_max_chars"), 190)
        self.assertEqual(effective_config_dict(loaded)["chat"]["response_max_chars"], 190)


if __name__ == "__main__":
    unittest.main()
