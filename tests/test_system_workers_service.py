import unittest

from core.system_workers_service import WorkerHealthDeps
from core.system_workers_service import build_docker_diagram_payload
from core.system_workers_service import collect_edge_workers
from core.system_workers_service import probe_worker_health


class _Response:
    def __init__(self, success: bool, status_code: int, payload: dict[str, object]) -> None:
        self.is_success = success
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, object]:
        return dict(self._payload)


class SystemWorkersServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_probe_worker_health_returns_loopback_for_api(self) -> None:
        async def _integrations() -> dict[str, object]:
            raise AssertionError("unused")

        async def _ipc_health(_service: str, _base: str, _timeout: float) -> _Response:
            raise AssertionError("unused")

        status, detail = await probe_worker_health(
            "api",
            "http://127.0.0.1:5010",
            deps=WorkerHealthDeps(integrations_snapshot=_integrations, ipc_health=_ipc_health),
        )

        self.assertEqual((status, detail), ("ok", "loopback"))

    async def test_probe_worker_health_uses_integrations_for_picobot(self) -> None:
        async def _integrations() -> dict[str, object]:
            return {"picobot": {"status": "running", "detail": "bridge ok"}}

        async def _ipc_health(_service: str, _base: str, _timeout: float) -> _Response:
            raise AssertionError("unused")

        status, detail = await probe_worker_health(
            "picobot",
            "http://127.0.0.1:3901",
            deps=WorkerHealthDeps(integrations_snapshot=_integrations, ipc_health=_ipc_health),
        )

        self.assertEqual(status, "running")
        self.assertEqual(detail, "bridge ok")

    async def test_collect_edge_workers_builds_expected_payload(self) -> None:
        calls: list[tuple[str, str, float]] = []

        async def _integrations() -> dict[str, object]:
            return {"picobot": {"status": "degraded", "detail": "bridge slow"}}

        async def _ipc_health(service: str, base: str, timeout: float) -> _Response:
            calls.append((service, base, timeout))
            return _Response(
                True,
                200,
                {"status": "ok", "detail": "healthy"},
            )

        workers = await collect_edge_workers(
            [
                {
                    "name": "didier-api",
                    "service": "api",
                    "label": "Worker API",
                    "fallback_base": "http://127.0.0.1:5010",
                    "meta": "FastAPI 5010",
                    "worker_type": "gateway",
                    "ipc": "unix+http",
                },
                {
                    "name": "didier-brain",
                    "service": "brain",
                    "label": "Worker Brain",
                    "fallback_base": "http://127.0.0.1:5012",
                    "meta": "Brain 5012",
                    "worker_type": "cognition",
                    "ipc": "unix",
                },
                {
                    "name": "didier-picobot",
                    "service": "picobot",
                    "label": "Worker Picobot",
                    "fallback_base": "http://127.0.0.1:3901",
                    "meta": "Agent leger local",
                    "worker_type": "agentic",
                    "ipc": "http",
                },
            ],
            deps=WorkerHealthDeps(
                integrations_snapshot=_integrations,
                ipc_health=_ipc_health,
                timeout_s=0.5,
            ),
        )

        self.assertEqual(workers[0]["status"], "ok")
        self.assertEqual(workers[1]["detail"], "healthy")
        self.assertEqual(workers[2]["status"], "degraded")
        self.assertEqual(calls, [("brain", "http://127.0.0.1:5012", 0.5)])

    def test_build_docker_diagram_payload_keeps_workers_and_links(self) -> None:
        payload = build_docker_diagram_payload(
            containers=[{"name": "didier-api"}],
            workers=[{"name": "didier-api", "status": "ok"}],
            links=[{"from": "a", "to": "b"}],
            now=12.5,
        )

        self.assertEqual(payload["ts"], 12.5)
        self.assertEqual(payload["containers"][0]["name"], "didier-api")
        self.assertEqual(payload["workers"][0]["status"], "ok")
        self.assertEqual(payload["links"][0]["from"], "a")


if __name__ == "__main__":
    unittest.main()
