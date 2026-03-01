"""Terminal execution policy for system routes."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from typing import Callable


@dataclass(frozen=True)
class TerminalExecError(Exception):
    status_code: int
    detail: str

    def __str__(self) -> str:
        return self.detail


def parse_terminal_command(
    payload: dict[str, Any] | None,
    *,
    max_chars: int,
    blocked_snippets: tuple[str, ...] | list[str],
) -> str:
    command = str((payload or {}).get("command", "")).strip()
    if not command:
        raise TerminalExecError(status_code=400, detail="command required")
    if len(command) > int(max_chars):
        raise TerminalExecError(status_code=400, detail="command too long")
    if any(char in command for char in ("\n", "\r", "\x00")):
        raise TerminalExecError(status_code=400, detail="multiline command not allowed")
    lower_command = command.lower()
    if any(str(snippet).lower() in lower_command for snippet in blocked_snippets):
        raise TerminalExecError(status_code=400, detail="command blocked")
    return command


def _truncate_output(output: str, *, max_output_chars: int) -> str:
    if len(output) <= int(max_output_chars):
        return output
    return output[: int(max_output_chars)].rstrip() + "\n...[truncated]"


def execute_terminal_command(
    command: str,
    *,
    repo_root: Path,
    timeout_s: float,
    max_output_chars: int,
    now: Callable[[], float],
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    started = float(now())
    try:
        proc = runner(
            ["bash", "-lc", command],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise TerminalExecError(status_code=408, detail="command timeout")
    output = f"{proc.stdout or ''}{proc.stderr or ''}".strip()
    return {
        "ok": proc.returncode == 0,
        "command": command,
        "exit_code": proc.returncode,
        "elapsed_ms": int((float(now()) - started) * 1000),
        "output": _truncate_output(output, max_output_chars=max_output_chars),
        "cwd": str(repo_root),
    }
