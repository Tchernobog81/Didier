import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core.orchestrator import Orchestrator


class OrchestratorConfigTests(unittest.TestCase):
    def _write_config(self, payload: dict) -> Path:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "config.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_orchestrator_bootstraps_new_loader_in_compatibility_mode(self) -> None:
        path = self._write_config(
            {
                "chat": {
                    "response_max_chars": 175,
                },
                "vision": {
                    "primary_fallback_secondary": False,
                },
            }
        )

        with patch.dict("os.environ", {}, clear=True):
            orchestrator = Orchestrator(config_path=str(path))

        self.assertEqual(orchestrator.config.get("chat.response_max_chars"), 175)
        self.assertEqual(orchestrator.runtime_config.chat.response_max_chars, 175)
        self.assertFalse(orchestrator.runtime_config.vision.primary_fallback_secondary)
        self.assertEqual(
            orchestrator.loaded_config.get("vision.primary_fallback_secondary"),
            False,
        )
        self.assertEqual(orchestrator.config_path, path)
        self.assertTrue(orchestrator.config_fingerprint)

    def test_reload_config_refreshes_all_views(self) -> None:
        path = self._write_config(
            {
                "chat": {
                    "response_max_chars": 150,
                }
            }
        )

        with patch.dict("os.environ", {}, clear=True):
            orchestrator = Orchestrator(config_path=str(path))
            updated_payload = {
                "chat": {
                    "response_max_chars": 120,
                },
                "tts": {
                    "response_max_chars": 90,
                },
            }
            path.write_text(json.dumps(updated_payload), encoding="utf-8")
            before = orchestrator.config_fingerprint
            orchestrator.reload_config()

        self.assertNotEqual(before, orchestrator.config_fingerprint)
        self.assertEqual(orchestrator.config.get("chat.response_max_chars"), 120)
        self.assertEqual(orchestrator.runtime_config.chat.response_max_chars, 120)
        self.assertEqual(orchestrator.runtime_config.tts.response_max_chars, 90)


if __name__ == "__main__":
    unittest.main()
