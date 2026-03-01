import subprocess
import unittest
from pathlib import Path

from core.system_terminal_service import TerminalExecError
from core.system_terminal_service import execute_terminal_command
from core.system_terminal_service import parse_terminal_command


class _Proc:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SystemTerminalServiceTests(unittest.TestCase):
    def test_parse_terminal_command_rejects_blocked_snippet(self) -> None:
        with self.assertRaises(TerminalExecError) as ctx:
            parse_terminal_command(
                {"command": "rm -rf /tmp/foo"},
                max_chars=300,
                blocked_snippets=("rm -rf /", "mkfs"),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "command blocked")

    def test_parse_terminal_command_rejects_multiline(self) -> None:
        with self.assertRaises(TerminalExecError) as ctx:
            parse_terminal_command(
                {"command": "echo a\necho b"},
                max_chars=300,
                blocked_snippets=(),
            )

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail, "multiline command not allowed")

    def test_execute_terminal_command_truncates_output(self) -> None:
        times = iter([10.0, 10.25])

        result = execute_terminal_command(
            "echo test",
            repo_root=Path("/tmp/repo"),
            timeout_s=2.0,
            max_output_chars=10,
            now=lambda: next(times),
            runner=lambda *_args, **_kwargs: _Proc(0, stdout="0123456789abcdef"),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["elapsed_ms"], 250)
        self.assertTrue(result["output"].endswith("...[truncated]"))
        self.assertEqual(result["cwd"], "/tmp/repo")

    def test_execute_terminal_command_maps_timeout(self) -> None:
        with self.assertRaises(TerminalExecError) as ctx:
            execute_terminal_command(
                "sleep 10",
                repo_root=Path("/tmp/repo"),
                timeout_s=1.0,
                max_output_chars=20,
                now=lambda: 0.0,
                runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    subprocess.TimeoutExpired(cmd=["bash"], timeout=1.0)
                ),
            )

        self.assertEqual(ctx.exception.status_code, 408)
        self.assertEqual(ctx.exception.detail, "command timeout")


if __name__ == "__main__":
    unittest.main()
