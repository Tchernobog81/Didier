"""System service control primitives shared by system routes."""

from __future__ import annotations

import asyncio
import subprocess
from typing import Awaitable
from typing import Callable


async def run_systemctl(
    *args: str,
    timeout_s: float = 2.0,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> tuple[int, str]:
    cmd = ["sudo", "-n", "systemctl", *args]

    def _run() -> subprocess.CompletedProcess[str]:
        return runner(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=float(timeout_s),
        )

    proc = await asyncio.to_thread(_run)
    detail = (proc.stdout or proc.stderr or "").strip()
    return proc.returncode, detail


async def service_state(
    service: str,
    *,
    timeout_s: float = 2.0,
    run_systemctl_fn: Callable[..., Awaitable[tuple[int, str]]] = run_systemctl,
) -> tuple[bool, str]:
    rc, detail = await run_systemctl_fn("is-active", str(service), timeout_s=float(timeout_s))
    state = (detail or "unknown").splitlines()[0].strip().lower()
    if rc == 0 and state in {"active", "activating"}:
        return True, state
    if not state:
        state = "inactive"
    return False, state
