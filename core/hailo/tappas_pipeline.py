"""TAPPAS pipeline wrapper with safe native fallback."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time
from typing import Any

from .monitor import detect_hailo


@dataclass
class TappasPipeline:
    """Native TAPPAS runner when available, safe stub otherwise."""

    enabled: bool = field(default_factory=detect_hailo)
    started: bool = False
    frames_seen: int = 0
    command: list[str] | None = None
    last_error: str | None = None
    _proc: subprocess.Popen[str] | None = None
    _started_at: float | None = None

    @property
    def is_available(self) -> bool:
        return self.enabled

    def _build_commands(self) -> list[list[str]]:
        env_cmd = os.getenv("DIDIER_TAPPAS_COMMAND", "").strip()
        if env_cmd:
            return [shlex.split(env_cmd)]

        if shutil.which("gst-launch-1.0") is None:
            return []

        commands: list[list[str]] = []
        hef_path = os.getenv("DIDIER_HAILO_HEF", "models/hailo/hailo_model.hef")
        video_dev = os.getenv("DIDIER_VISION_DEVICE", "/dev/video0")
        width = os.getenv("DIDIER_VISION_WIDTH", "640")
        height = os.getenv("DIDIER_VISION_HEIGHT", "480")
        fps = os.getenv("DIDIER_VISION_FPS", "30")
        if Path(hef_path).exists():
            commands.append(
                [
                    "gst-launch-1.0",
                    "-q",
                    "v4l2src",
                    f"device={video_dev}",
                    "!",
                    f"video/x-raw,width={width},height={height},framerate={fps}/1",
                    "!",
                    "videoconvert",
                    "!",
                    "hailonet",
                    f"hef-path={hef_path}",
                    "!",
                    "fakesink",
                    "sync=false",
                ]
            )
        else:
            self.last_error = f"hef_missing:{hef_path}"

        # Optional fallback disabled by default on boards where hailodevicestats is unsupported.
        if os.getenv("DIDIER_TAPPAS_STATS_FALLBACK", "0").strip() in {"1", "true", "yes", "on"}:
            commands.append(
                ["gst-launch-1.0", "-q", "hailodevicestats", "interval=2", "silent=false"]
            )
        return commands

    def start(self) -> bool:
        if not self.enabled:
            self.started = False
            return False

        for cmd in self._build_commands():
            try:
                proc = subprocess.Popen(  # nosec B603
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                )
                time.sleep(0.8)
                if proc.poll() is None:
                    self._proc = proc
                    self.command = cmd
                    self.started = True
                    self._started_at = time.time()
                    self.last_error = None
                    return True
                err = ""
                if proc.stderr:
                    err = (proc.stderr.read() or "").strip()
                self.last_error = err or f"command exited ({proc.returncode})"
            except Exception as exc:
                self.last_error = str(exc)
                continue

        if self.last_error is None:
            self.last_error = "no_tappas_command"
        self.started = False
        return False

    def stop(self) -> None:
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=2)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None
        self.started = False

    def process_frame(self, frame: Any) -> list[dict[str, Any]]:
        # Detection output wiring is handled by existing vision code path for now.
        if not self.enabled:
            return []
        self.frames_seen += 1
        return []

    def status(self) -> dict[str, Any]:
        running = bool(self._proc and self._proc.poll() is None)
        if self.started and not running:
            self.started = False
            if self.last_error is None:
                self.last_error = "pipeline_exited"
        return {
            "backend": "tappas_native" if self.started else "tappas_stub",
            "enabled": self.enabled,
            "started": self.started,
            "frames_seen": self.frames_seen,
            "command": " ".join(self.command) if self.command else None,
            "uptime_s": round(time.time() - self._started_at, 3) if self._started_at else 0.0,
            "last_error": self.last_error,
        }
