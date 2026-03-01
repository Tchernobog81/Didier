import subprocess
import unittest

from core.system_service_control import run_systemctl
from core.system_service_control import service_state


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SystemServiceControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_systemctl_returns_rc_and_detail(self) -> None:
        calls: list[list[str]] = []

        def _runner(cmd, **_kwargs):
            calls.append(list(cmd))
            return _Proc(0, stdout="active\n")

        rc, detail = await run_systemctl("is-active", "didier-api.service", runner=_runner)

        self.assertEqual(rc, 0)
        self.assertEqual(detail, "active")
        self.assertEqual(calls, [["sudo", "-n", "systemctl", "is-active", "didier-api.service"]])

    async def test_service_state_marks_active_and_inactive(self) -> None:
        async def _ok_run(*_args, **_kwargs):
            return 0, "active"

        async def _bad_run(*_args, **_kwargs):
            return 3, ""

        self.assertEqual(
            await service_state("didier-api.service", run_systemctl_fn=_ok_run),
            (True, "active"),
        )
        self.assertEqual(
            await service_state("didier-api.service", run_systemctl_fn=_bad_run),
            (False, "unknown"),
        )

    async def test_run_systemctl_propagates_runner_errors(self) -> None:
        def _runner(_cmd, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=["systemctl"], timeout=1.0)

        with self.assertRaises(subprocess.TimeoutExpired):
            await run_systemctl("status", "didier-api.service", runner=_runner)


if __name__ == "__main__":
    unittest.main()
