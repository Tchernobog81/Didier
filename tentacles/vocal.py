import asyncio
import logging
import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf
from kokoro_onnx import Kokoro

from tentacles.base import BaseTentacle
from core.status import update_status


class Tentacle(BaseTentacle):
    name = "vocal"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(f"Tentacle.{self.name}")
        self._sink = self.config.get(
            "bluetooth.sink_name", "bluez_output.00_07_80_E0_3F_F0.1"
        )
        self._mac_address = self.config.get("bluetooth.mac_address", "")
        self._model_path = Path(
            self.config.get("tts.model_path", "voices/kokoro-v1.0.onnx")
        )
        self._config_path = Path(
            self.config.get("tts.config_path", "voices/kokoro-v1.0.json")
        )
        self._output_path = Path(
            self.config.get("tts.output_path", "data/didier_speaks.wav")
        )
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._kokoro: Optional[Kokoro] = None
        self._enabled = True

    async def start(self) -> None:
        await self._load_model()
        await super().start()

    async def run(self) -> None:
        if not self._enabled:
            self._logger.warning("Vocal tentacle disabled.")
            await self.stop_event.wait()
            return

        self._logger.info("Vocal tentacle ready (sink=%s).", self._sink)
        while not self.stop_event.is_set():
            try:
                text = await asyncio.wait_for(self._queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            await self._synthesize_and_play(text)

    async def speak(self, text: str) -> None:
        if not self._enabled:
            self._logger.warning("Vocal tentacle disabled; dropping speech.")
            return
        await self._queue.put(text)

    async def beep(self) -> None:
        if not self._enabled:
            return
        await asyncio.to_thread(self._play_beep)

    async def _load_model(self) -> None:
        if not self._model_path.exists() or not self._config_path.exists():
            self._logger.error(
                "Missing Kokoro model/config: %s %s",
                self._model_path,
                self._config_path,
            )
            self._enabled = False
            return

        try:
            self._kokoro = await asyncio.to_thread(
                Kokoro, model=str(self._model_path), config_path=str(self._config_path)
            )
        except Exception:
            self._logger.exception("Failed to initialize Kokoro.")
            self._enabled = False

    async def _synthesize_and_play(self, text: str) -> None:
        if not self._kokoro:
            self._logger.error("Kokoro not initialized.")
            return

        try:
            update_status(speaking=True, state="SPEAKING", last_speak_at=time.time())
            wav_data, sample_rate = await asyncio.to_thread(
                self._kokoro.get_speech_ary, text
            )
            self._output_path.parent.mkdir(parents=True, exist_ok=True)
            await asyncio.to_thread(
                sf.write, str(self._output_path), wav_data, sample_rate
            )
            await asyncio.to_thread(self._play_audio)
        except Exception:
            self._logger.exception("Failed to synthesize or play speech.")
        finally:
            update_status(speaking=False, state="IDLE")

    def _play_audio(self) -> None:
        self._play_audio_path(self._output_path)

    def _play_beep(self) -> None:
        if not shutil.which("paplay"):
            self._logger.error("paplay is not available in PATH.")
            return
        sample_rate = 22050
        duration = 0.18
        t = np.linspace(0, duration, int(sample_rate * duration), False)
        tone = 0.6 * np.sin(2 * np.pi * 880 * t)
        envelope = np.exp(-t * 18)
        audio = (tone * envelope).astype(np.float32)
        path = Path("/tmp/didier_beep.wav")
        try:
            sf.write(str(path), audio, sample_rate)
            self._play_audio_path(path)
        finally:
            try:
                if path.exists():
                    path.unlink()
            except Exception:
                pass

    def _play_audio_path(self, path: Path) -> None:
        if not shutil.which("paplay"):
            self._logger.error("paplay is not available in PATH.")
            return
        try:
            subprocess.run(["paplay", "-d", self._sink, str(path)], check=True)
        except subprocess.CalledProcessError:
            self._logger.warning("paplay failed, attempting Bluetooth reconnect.")
            if self._reconnect_bluetooth():
                try:
                    subprocess.run(["paplay", "-d", self._sink, str(path)], check=True)
                    return
                except subprocess.CalledProcessError:
                    self._logger.exception("paplay failed after reconnect.")
            else:
                self._logger.exception("Bluetooth reconnect failed.")

    def _reconnect_bluetooth(self) -> bool:
        if not self._mac_address:
            return False
        if not shutil.which("bluetoothctl"):
            self._logger.error("bluetoothctl not available in PATH.")
            return False
        mac = self._mac_address.strip()
        if mac.endswith(".1"):
            mac = mac.rsplit(".", 1)[0]
        try:
            result = subprocess.run(
                ["bluetoothctl", "connect", mac],
                capture_output=True,
                text=True,
                check=False,
            )
            if result.returncode != 0:
                self._logger.warning(
                    "bluetoothctl connect failed: %s",
                    (result.stderr or result.stdout or "").strip(),
                )
                return False
            time.sleep(1)
            return True
        except Exception:
            self._logger.exception("bluetoothctl reconnect error.")
            return False
