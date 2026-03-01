import unittest

from core.ai_backend_policy import candidate_picobot_bases
from core.ai_backend_policy import resolve_generate_timeout
from core.ai_backend_policy import resolve_gemini_boost_config
from core.ai_backend_policy import resolve_local_fallback_timeout
from core.config_schema import OllamaConfig
from core.config_schema import PicobotConfig
from core.config_schema import RoutingConfig


class AIBackendPolicyTests(unittest.TestCase):
    def test_resolve_generate_timeout_respects_pixel_override_and_caps(self) -> None:
        ollama_config = OllamaConfig(timeout_seconds=120.0)
        routing_config = RoutingConfig.from_mapping(
            {
                "pixel_ollama": {
                    "generate_timeout_s": 4.2,
                }
            }
        )

        local_timeout = resolve_generate_timeout(
            ollama_config,
            routing_config,
            {"execution_backend": "local_ollama"},
        )
        pixel_timeout = resolve_generate_timeout(
            ollama_config,
            routing_config,
            {"execution_backend": "pixel_ollama"},
        )

        self.assertEqual(local_timeout, 7.0)
        self.assertEqual(pixel_timeout, 4.2)

    def test_resolve_local_fallback_timeout_uses_dynamic_default_or_explicit_value(self) -> None:
        dynamic = resolve_local_fallback_timeout(
            RoutingConfig(),
            primary_timeout_s=4.0,
        )
        explicit = resolve_local_fallback_timeout(
            RoutingConfig.from_mapping(
                {
                    "local_ollama": {
                        "fallback_timeout_s": 2.6,
                    }
                }
            ),
            primary_timeout_s=4.0,
        )

        self.assertEqual(dynamic, 2.0)
        self.assertEqual(explicit, 2.6)

    def test_candidate_picobot_bases_dedupes_and_filters_local_api(self) -> None:
        picobot_config = PicobotConfig.from_mapping(
            {
                "base_url": "http://192.168.1.50:5012",
            }
        )

        bases = candidate_picobot_bases(
            picobot_config,
            fallback_bases=(
                "http://192.168.1.50:5012",
                "http://127.0.0.1:5010",
                "http://127.0.0.1:3901",
            ),
        )

        self.assertEqual(
            bases,
            [
                "http://192.168.1.50:5012",
                "http://127.0.0.1:3901",
            ],
        )

    def test_resolve_gemini_boost_config_applies_env_api_key_override(self) -> None:
        picobot_config = PicobotConfig.from_mapping(
            {
                "gemini": {
                    "enabled": True,
                    "api_key": "config-key",
                    "memory_items": 4,
                }
            }
        )

        resolved = resolve_gemini_boost_config(
            picobot_config,
            env={"DIDIER_GEMINI_API_KEY": "env-key"},
        )

        self.assertTrue(resolved["enabled"])
        self.assertEqual(resolved["api_key"], "env-key")
        self.assertEqual(resolved["memory_items"], 4)


if __name__ == "__main__":
    unittest.main()
