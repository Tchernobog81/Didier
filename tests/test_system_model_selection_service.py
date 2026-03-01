import json
import tempfile
import unittest
from pathlib import Path

from core.system_model_selection_service import ModelSelectionError
from core.system_model_selection_service import ModelSelectionRequest
from core.system_model_selection_service import apply_model_selection
from core.system_model_selection_service import build_current_models_payload
from core.system_model_selection_service import parse_model_selection_request
from core.system_model_selection_service import read_runtime_config
from core.system_model_selection_service import write_runtime_config


class SystemModelSelectionServiceTests(unittest.TestCase):
    def test_parse_model_selection_request_rejects_invalid_model(self) -> None:
        with self.assertRaises(ModelSelectionError) as ctx:
            parse_model_selection_request(
                {"task_type": "chat", "model": "bad\nmodel"},
                selectable_tasks={"chat", "coding"},
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "invalid model value")

    def test_apply_model_selection_updates_chat_profiles(self) -> None:
        request = ModelSelectionRequest(
            task_type="chat",
            model="qwen2.5:3b",
            backend=None,
            allow_unbenchmarked=False,
        )
        updated, applied = apply_model_selection(
            {
                "llmfit": {"task_profiles": {}},
                "ollama": {"model_profiles": {}},
            },
            request,
            {"backend": "ollama", "score": "good"},
            selected_at=42.0,
        )

        self.assertEqual(updated["llmfit"]["task_profiles"]["chat"]["model"], "qwen2.5:3b")
        self.assertEqual(updated["llmfit"]["task_profiles"]["chat"]["backend"], "ollama")
        self.assertEqual(updated["llmfit"]["task_profiles"]["chat"]["score"], "good")
        self.assertEqual(updated["ollama"]["model_profiles"]["ask"], "qwen2.5:3b")
        self.assertEqual(updated["ollama"]["model"], "qwen2.5:3b")
        self.assertEqual(updated["ollama"]["model_selected_at"], 42.0)
        self.assertTrue(applied["benchmarked"])
        self.assertEqual(applied["score"], "good")

    def test_build_current_models_payload_exposes_selected_profiles(self) -> None:
        payload = build_current_models_payload(
            {
                "ollama": {
                    "model": "qwen2.5:3b",
                    "model_profiles": {"ask": "qwen2.5:3b", "coding": "qwen2.5-coder:7b"},
                    "model_selected_at": 12.5,
                },
                "llmfit": {
                    "task_profiles": {
                        "chat": {"backend": "ollama", "model": "qwen2.5:3b", "score": "good"},
                    }
                },
            }
        )

        self.assertEqual(payload["default"], "qwen2.5:3b")
        self.assertEqual(payload["ask"], "qwen2.5:3b")
        self.assertEqual(payload["coding"], "qwen2.5-coder:7b")
        self.assertEqual(payload["selected_at"], 12.5)
        self.assertEqual(payload["llmfit_profiles"]["chat"]["backend"], "ollama")

    def test_read_and_write_runtime_config_round_trip(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        config_path = Path(temp_dir.name) / "config.json"

        write_runtime_config(config_path, {"chat": {"response_max_chars": 123}})
        loaded = read_runtime_config(config_path)

        self.assertEqual(loaded["chat"]["response_max_chars"], 123)
        self.assertEqual(
            json.loads(config_path.read_text(encoding="utf-8"))["chat"]["response_max_chars"],
            123,
        )


if __name__ == "__main__":
    unittest.main()
