import tempfile
import unittest
from pathlib import Path

from core.system_integrations_service import IntegrationsSnapshotCollector
from core.system_integrations_service import IntegrationsSnapshotDeps
from core.system_integrations_service import resolve_signal_base_url
from core.system_integrations_service import rollup_status


class SystemIntegrationsServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_collector_returns_offline_when_orchestrator_unavailable(self) -> None:
        def _missing_orchestrator():
            raise RuntimeError("no orchestrator")

        async def _unused_service_state(_service: str) -> tuple[bool, str]:
            raise AssertionError("unused")

        collector = IntegrationsSnapshotCollector(cache_ttl_s=5.0)
        deps = IntegrationsSnapshotDeps(
            get_orchestrator=_missing_orchestrator,
            service_state=_unused_service_state,
            runtime_config_path=Path("/tmp/missing-config.json"),
            repo_root=Path("/tmp"),
        )

        result = await collector.collect(force=False, deps=deps)

        self.assertEqual(result["status"], "offline")
        self.assertEqual(result["picobot"]["detail"], "orchestrator unavailable")
        self.assertEqual(result["ollama"]["detail"], "orchestrator unavailable")
        self.assertEqual(result["signal"]["detail"], "orchestrator unavailable")

    async def test_collector_uses_cache_between_calls(self) -> None:
        now_holder = {"value": 10.0}
        calls: list[str] = []

        async def _fake_picobot(_orchestrator, **_kwargs):
            calls.append("picobot")
            return {"status": "running", "detail": "ok"}

        async def _fake_ollama(_orchestrator, **_kwargs):
            calls.append("ollama")
            return {"status": "running", "detail": "ok"}

        async def _fake_signal(**_kwargs):
            calls.append("signal")
            return {"status": "offline", "detail": "down"}

        async def _unused_service_state(_service: str) -> tuple[bool, str]:
            raise AssertionError("unused")

        collector = IntegrationsSnapshotCollector(
            cache_ttl_s=5.0,
            now=lambda: now_holder["value"],
            probe_picobot_fn=_fake_picobot,
            probe_ollama_fn=_fake_ollama,
            probe_signal_fn=_fake_signal,
        )
        deps = IntegrationsSnapshotDeps(
            get_orchestrator=lambda: object(),
            service_state=_unused_service_state,
            runtime_config_path=Path("/tmp/config.json"),
            repo_root=Path("/tmp"),
        )

        first = await collector.collect(force=False, deps=deps)
        now_holder["value"] = 12.0
        second = await collector.collect(force=False, deps=deps)

        self.assertEqual(first["status"], "degraded")
        self.assertEqual(second["status"], "degraded")
        self.assertEqual(calls, ["picobot", "ollama", "signal"])


class SystemIntegrationsHelpersTests(unittest.TestCase):
    def test_rollup_status_marks_mixed_states_degraded(self) -> None:
        self.assertEqual(rollup_status(["running", "offline", "running"]), "degraded")
        self.assertEqual(rollup_status(["running", "running", "running"]), "running")
        self.assertEqual(rollup_status(["offline", "offline"]), "offline")

    def test_resolve_signal_base_url_prefers_config_when_env_absent(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        path = Path(temp_dir.name) / "config.json"
        path.write_text('{"signal":{"base_url":"http://127.0.0.1:8090"}}', encoding="utf-8")

        resolved = resolve_signal_base_url(path, env_get=lambda _key, default="": default)

        self.assertEqual(resolved, "http://127.0.0.1:8090")


if __name__ == "__main__":
    unittest.main()
