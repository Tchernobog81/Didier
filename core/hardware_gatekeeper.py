"""Cross-process hardware gatekeeper for camera and NPU access."""

from __future__ import annotations

import fcntl
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

_LOCK_DIR = Path(os.getenv("DIDIER_HW_LOCK_DIR", "/tmp"))
_POLL_INTERVAL_S = 0.05


@dataclass
class HardwareLease:
    """Represents a held hardware gate."""

    resource: str
    _manager: "HardwareGatekeeper"
    _released: bool = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._manager.release(self.resource)

    def __enter__(self) -> "HardwareLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
        self.release()


class HardwareGatekeeper:
    """Singleton lock manager backed by POSIX flock files."""

    _instance: "HardwareGatekeeper | None" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> "HardwareGatekeeper":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def __init__(self) -> None:
        self._state_lock = threading.Lock()
        self._held: dict[str, dict[str, object]] = {}

    def _lock_path(self, resource: str) -> Path:
        safe = "".join(ch for ch in str(resource).strip().lower() if ch.isalnum() or ch in {"_", "-"})
        safe = safe or "unknown"
        return _LOCK_DIR / f"didier_hw_{safe}.lock"

    def acquire(
        self,
        resource: str,
        *,
        timeout_s: float = 0.2,
        blocking: bool = False,
    ) -> HardwareLease | None:
        key = str(resource or "").strip().lower()
        if not key:
            return None
        timeout_s = max(0.0, float(timeout_s))
        pid = os.getpid()

        with self._state_lock:
            current = self._held.get(key)
            if current and int(current["pid"]) == pid:
                current["count"] = int(current["count"]) + 1
                return HardwareLease(resource=key, _manager=self)

        deadline = time.monotonic() + timeout_s
        lock_path = self._lock_path(key)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        while True:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self._state_lock:
                    existing = self._held.get(key)
                    if existing and int(existing["pid"]) == pid:
                        existing["count"] = int(existing["count"]) + 1
                        fcntl.flock(fd, fcntl.LOCK_UN)
                        os.close(fd)
                        return HardwareLease(resource=key, _manager=self)
                    self._held[key] = {"pid": pid, "count": 1, "fd": fd}
                return HardwareLease(resource=key, _manager=self)
            except BlockingIOError:
                os.close(fd)
                if not blocking and time.monotonic() >= deadline:
                    return None
                if blocking and timeout_s <= 0:
                    continue
                if time.monotonic() >= deadline:
                    return None
                time.sleep(_POLL_INTERVAL_S)
            except Exception:
                os.close(fd)
                return None

    def release(self, resource: str) -> None:
        key = str(resource or "").strip().lower()
        if not key:
            return
        fd: int | None = None
        with self._state_lock:
            current = self._held.get(key)
            if not current:
                return
            current["count"] = int(current["count"]) - 1
            if int(current["count"]) > 0:
                return
            fd = int(current["fd"])
            self._held.pop(key, None)
        if fd is None:
            return
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        try:
            os.close(fd)
        except Exception:
            pass

    def is_held(self, resource: str) -> bool:
        key = str(resource or "").strip().lower()
        if not key:
            return False
        with self._state_lock:
            current = self._held.get(key)
            return bool(current and int(current.get("count", 0)) > 0)


def get_hardware_gatekeeper() -> HardwareGatekeeper:
    return HardwareGatekeeper.get_instance()
