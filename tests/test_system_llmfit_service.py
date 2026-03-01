import unittest

from core.system_llmfit_service import LLMFitReportCollector
from core.system_llmfit_service import build_llmfit_recommendation
from core.system_llmfit_service import llmfit_context_from_state


class SystemLLMFitServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_collector_builds_running_report_and_uses_cache(self) -> None:
        now_holder = {"value": 10.0}
        read_calls = {"count": 0}
        best_calls: list[str] = []

        def _read_state() -> dict[str, object]:
            read_calls["count"] += 1
            return {
                "hardware_profile": {"npu": {"available": True, "device_count": 1}},
                "metrics": {"cpu": {"percent": 12.0}, "memory": {"percent": 34.0}},
            }

        def _get_best_model(task_type: str, context: dict[str, object]) -> dict[str, object]:
            best_calls.append(task_type)
            return {
                "backend": "ollama",
                "model": f"{task_type}-model",
                "score": "good",
                "provider": "llmfit",
                "source": "llmfit",
                "reason": f"{task_type} ok",
            }

        collector = LLMFitReportCollector(
            cache_ttl_s=5.0,
            task_samples=(("chat", "bonjour"), ("coding", "fibonacci")),
            read_shared_state_fn=_read_state,
            get_best_model_fn=_get_best_model,
            default_timeout_s=2.0,
            now=lambda: now_holder["value"],
        )

        first = await collector.collect(force=False)
        now_holder["value"] = 12.0
        second = await collector.collect(force=False)

        self.assertTrue(first["ok"])
        self.assertEqual(first["status"], "running")
        self.assertEqual(first["summary"]["tasks_total"], 2)
        self.assertEqual(first["summary"]["llmfit_hits"], 2)
        self.assertEqual(second["status"], "running")
        self.assertEqual(read_calls["count"], 1)
        self.assertEqual(best_calls, ["chat", "coding"])

    async def test_collector_returns_offline_on_failure(self) -> None:
        collector = LLMFitReportCollector(
            cache_ttl_s=5.0,
            task_samples=(("chat", "bonjour"),),
            read_shared_state_fn=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            get_best_model_fn=lambda _task, _ctx: {},
            now=lambda: 5.0,
        )

        result = await collector.collect(force=False)

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["summary"]["tasks_total"], 0)
        self.assertIn("boom", result["error"])


class SystemLLMFitHelpersTests(unittest.TestCase):
    def test_llmfit_context_from_state_extracts_metrics(self) -> None:
        context = llmfit_context_from_state(
            {
                "hardware_profile": {
                    "npu": {"available": True, "device_count": 2},
                    "tpu": {"pixel_detected": True, "pixel_count": 1},
                },
                "metrics": {
                    "cpu": {"percent": 22.5},
                    "memory": {"percent": 55.0},
                },
            }
        )

        self.assertTrue(context["npu_available"])
        self.assertEqual(context["npu_device_count"], 2)
        self.assertTrue(context["pixel_detected"])
        self.assertEqual(context["cpu_percent"], 22.5)
        self.assertEqual(context["memory_percent"], 55.0)

    def test_build_llmfit_recommendation_shapes_result(self) -> None:
        recommendation = build_llmfit_recommendation(
            "chat",
            "Bonjour Didier",
            {"cpu_percent": 12.0},
            get_best_model=lambda _task, _ctx: {
                "backend": "ollama",
                "model": "qwen2.5:3b",
                "score": "perfect",
                "provider": "llmfit",
                "source": "llmfit",
                "reason": "stable",
            },
            default_timeout_s=2.0,
            now=lambda: 42.0,
        )

        self.assertEqual(recommendation["task_type"], "chat")
        self.assertEqual(recommendation["score_bucket"], "perfect")
        self.assertEqual(recommendation["timeout_s"], 2.0)
        self.assertEqual(recommendation["ts"], 42.0)


if __name__ == "__main__":
    unittest.main()
