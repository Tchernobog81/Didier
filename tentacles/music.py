import asyncio
import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from tentacles.base import BaseTentacle


class Tentacle(BaseTentacle):
    name = "music"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(f"Tentacle.{self.name}")
        self._sink = self.config.get(
            "bluetooth.sink_name", "bluez_output.00_07_80_E0_3F_F0.1"
        )
        self._enabled = bool(self.config.get("music.enabled", False))
        self._model_dir = Path(self.config.get("music.model_dir", "models/musicgen-small-onnx"))
        self._output_path = Path(self.config.get("music.output_path", "data/music.wav"))
        self._subprocess_timeout_s = max(
            0.1,
            min(float(self.config.get("music.subprocess_timeout_seconds", 2.0)), 2.0),
        )
        self._queue_maxsize = max(1, int(self.config.get("music.queue_maxsize", 8)))
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=self._queue_maxsize)

    async def run(self) -> None:
        if not self._enabled:
            self._logger.info("Music tentacle disabled.")
            await self.stop_event.wait()
            return
        self._logger.info("Music tentacle ready (sink=%s).", self._sink)
        while not self.stop_event.is_set():
            try:
                prompt = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            await self._generate_and_play(prompt)

    async def play(self, prompt: str) -> None:
        if not self._enabled:
            self._logger.warning("Music tentacle disabled; dropping request.")
            return
        try:
            self._queue.put_nowait(prompt)
        except asyncio.QueueFull:
            self._logger.warning("Music queue saturated, dropping request.")

    async def _generate_and_play(self, prompt: str) -> None:
        if self._model_dir.exists():
            self._logger.info("Music request received: %s", prompt)
        else:
            self._logger.warning("Music model directory not found: %s", self._model_dir)
        try:
            audio, sample_rate = await asyncio.to_thread(self._render_stub_music)
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(sf.write, str(self._output_path), audio, sample_rate)
            await asyncio.to_thread(self._play_audio)
        except Exception:
            self._logger.exception("Failed to generate/play music.")

    def _render_stub_music(self) -> tuple[np.ndarray, int]:
        sample_rate = 22050
        notes = [261.63, 329.63, 392.0, 523.25, 392.0, 329.63, 261.63]
        durations = [0.35, 0.35, 0.35, 0.5, 0.35, 0.35, 0.5]
        audio = np.zeros(0, dtype=np.float32)
        for freq, dur in zip(notes, durations):
            t = np.linspace(0, dur, int(sample_rate * dur), False)
            tone = 0.2 * np.sin(2 * np.pi * freq * t)
            envelope = np.linspace(1.0, 0.2, tone.size)
            audio = np.concatenate([audio, (tone * envelope).astype(np.float32)])
            audio = np.concatenate([audio, np.zeros(int(sample_rate * 0.05), dtype=np.float32)])
        return audio, sample_rate

    def _play_audio(self) -> None:
        if not shutil.which("paplay"):
            self._logger.error("paplay is not available in PATH.")
            return
        try:
            subprocess.run(
                ["paplay", "-d", self._sink, str(self._output_path)],
                check=True,
                timeout=self._subprocess_timeout_s,
            )
        except subprocess.CalledProcessError:
            self._logger.exception("paplay failed.")
