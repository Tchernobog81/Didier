import asyncio
import logging
import os
import re
import shutil
import subprocess
import time
import threading
from pathlib import Path
import unicodedata

import numpy as np
import soundfile as sf

from tentacles.base import BaseTentacle
from core.status import update_status


class Tentacle(BaseTentacle):
    name = "hearing"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._enabled = bool(self.config.get("asr.enabled", False))
        self._alsa_device = self.config.get("asr.alsa_device", "default")
        self._sample_rate = int(self.config.get("asr.sample_rate", 16000))
        self._chunk_seconds = int(self.config.get("asr.chunk_seconds", 5))
        self._channels = int(self.config.get("asr.channels", 4))
        self._language = self.config.get("asr.language", "fr")
        self._whisper_bin = self.config.get("asr.whisper_cpp_bin", "")
        self._model_path = self.config.get("asr.model_path", "")
        self._wake_word = str(self.config.get("asr.wake_word", "")).strip()
        aliases = self.config.get("asr.wake_word_aliases", []) or []
        self._wake_words = [self._wake_word] + [str(x) for x in aliases if x]
        self._wake_word_norms = [
            self._normalize_text(w) for w in self._wake_words if w
        ]
        self._wake_word_compact = [w.replace(" ", "") for w in self._wake_word_norms if w]
        self._wake_word_norm = self._wake_word_norms[0] if self._wake_word_norms else ""
        self._wake_timeout = float(
            self.config.get("asr.wake_timeout_seconds", 12)
        )
        self._armed = False
        self._armed_until = 0.0
        self._data_dir = Path("data")
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._audio_queue: asyncio.Queue[Path] = asyncio.Queue(maxsize=2)
        self._capture_thread: threading.Thread | None = None
        self._capture_stop = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._tmp_dir = Path("/tmp")

    async def start(self) -> None:
        if self._enabled:
            self._loop = asyncio.get_running_loop()
            self._start_capture_thread()
        await super().start()

    async def stop(self) -> None:
        self._capture_stop.set()
        if self._capture_thread and self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2)
        await super().stop()

    async def run(self) -> None:
        if not self._enabled:
            self._logger.warning("Hearing tentacle disabled.")
            await self.stop_event.wait()
            return

        if not self._whisper_bin or not os.path.exists(self._whisper_bin):
            self._logger.error("whisper.cpp binary not found: %s", self._whisper_bin)
            await self.stop_event.wait()
            return

        if not self._model_path or not Path(self._model_path).exists():
            self._logger.error("whisper.cpp model not found: %s", self._model_path)
            await self.stop_event.wait()
            return

        self._logger.info("Hearing tentacle started.")
        self._write_status(listening=True, state="LISTENING")
        while not self.stop_event.is_set():
            try:
                wav_path = await asyncio.wait_for(self._audio_queue.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            text = await self._transcribe_wav(wav_path)
            if not text:
                continue
            if self._wake_word_norms:
                now = time.time()
                if self._matches_wake_word(text):
                    self._write_status(last_transcript=text, last_heard_at=now)
                    extra = self._extract_after_wake(text)
                    await self._on_wake_word(text)
                    if extra:
                        if self._roi_allows_interaction():
                            await self._handle_transcript(extra)
                            self._armed = False
                        else:
                            self._logger.info("ROI gating: no person in interaction zone.")
                            self._armed = False
                            self._write_status(state="IDLE")
                    continue
                if not self._armed or now > self._armed_until:
                    self._armed = False
                    self._write_status(state="IDLE")
                    continue
                self._write_status(last_transcript=text, last_heard_at=now)
            if not self._roi_allows_interaction():
                self._logger.info("ROI gating: no person in interaction zone.")
                self._armed = False
                self._write_status(state="IDLE")
                continue
            await self._handle_transcript(text)
            self._armed = False
        self._write_status(listening=False, state="IDLE")

    def _start_capture_thread(self) -> None:
        if self._capture_thread and self._capture_thread.is_alive():
            return
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True
        )
        self._capture_thread.start()

    def _capture_loop(self) -> None:
        if shutil.which("arecord") is None:
            self._logger.error("arecord not available.")
            return
        while not self._capture_stop.is_set():
            ts = int(time.time() * 1000)
            wav_path = self._tmp_dir / f"didier_mic_{ts}.wav"
            cmd = [
                "arecord",
                "-D",
                self._alsa_device,
                "-f",
                "S16_LE",
                "-c",
                str(self._channels),
                "-r",
                str(self._sample_rate),
                "-d",
                str(self._chunk_seconds),
                str(wav_path),
            ]
            try:
                subprocess.run(cmd, check=True, capture_output=True)
            except Exception as exc:
                self._logger.warning("arecord failed: %s", exc)
                time.sleep(0.5)
                continue
            if not wav_path.exists():
                continue
            if not self._loop:
                self._cleanup_path(wav_path)
                continue
            self._loop.call_soon_threadsafe(self._enqueue_wav, wav_path)

    def _enqueue_wav(self, wav_path: Path) -> None:
        if self._audio_queue.full():
            self._cleanup_path(wav_path)
            return
        try:
            self._audio_queue.put_nowait(wav_path)
        except asyncio.QueueFull:
            self._cleanup_path(wav_path)

    async def _transcribe_wav(self, wav_path: Path) -> str | None:
        mono_path = wav_path.with_name(f"{wav_path.stem}_mono.wav")
        txt_path = mono_path.with_suffix(".wav.txt")

        try:
            data, sr = await asyncio.to_thread(
                sf.read, str(wav_path), dtype="float32"
            )
            if data.ndim > 1:
                data = np.mean(data, axis=1)
            await asyncio.to_thread(sf.write, str(mono_path), data, sr)
        except Exception as exc:
            self._logger.warning("audio downmix failed: %s", exc)
            self._cleanup_path(wav_path)
            return None

        whisper_cmd = [
            self._whisper_bin,
            "-m",
            self._model_path,
            "-f",
            str(mono_path),
            "-l",
            self._language,
            "-otxt",
        ]
        try:
            await asyncio.to_thread(subprocess.run, whisper_cmd, check=True)
        except Exception as exc:
            self._logger.warning("whisper.cpp failed: %s", exc)
            self._cleanup_path(wav_path)
            self._cleanup_path(mono_path)
            self._cleanup_path(txt_path)
            return None

        if not txt_path.exists():
            self._cleanup_path(wav_path)
            self._cleanup_path(mono_path)
            return None

        text = txt_path.read_text(encoding="utf-8").strip()
        if not text:
            self._cleanup_path(wav_path)
            self._cleanup_path(mono_path)
            self._cleanup_path(txt_path)
            return None
        self._cleanup_path(wav_path)
        self._cleanup_path(mono_path)
        self._cleanup_path(txt_path)
        return text

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        normalized = unicodedata.normalize("NFKD", text)
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized.lower()).strip()
        return normalized

    def _matches_wake_word(self, text: str) -> bool:
        if not self._wake_word_norms:
            return False
        normalized = self._normalize_text(text)
        for wake in self._wake_word_norms:
            if wake and wake in normalized:
                return True
        compact = normalized.replace(" ", "")
        for wake in self._wake_word_compact:
            if wake and wake in compact:
                return True
        return False

    async def _on_wake_word(self, text: str) -> None:
        self._logger.info("Wake word detected.")
        self._armed = True
        self._armed_until = time.time() + self._wake_timeout
        self._write_status(state="LISTENING")
        orchestrator = self._orchestrator
        vocal = getattr(orchestrator, "get_tentacle", lambda name: None)("vocal")
        if vocal and hasattr(vocal, "beep"):
            try:
                await vocal.beep()
            except Exception:
                self._logger.debug("Wake word beep failed.", exc_info=True)

    def _extract_after_wake(self, text: str) -> str | None:
        if not self._wake_word_norms:
            return None
        normalized = self._normalize_text(text)
        for wake in self._wake_word_norms:
            if wake and wake in normalized:
                remainder = normalized.replace(wake, "").strip()
                return remainder or None
        return None

    def _roi_allows_interaction(self) -> bool:
        orchestrator = self._orchestrator
        vision = getattr(orchestrator, "get_tentacle", lambda name: None)("vision")
        require_roi = bool(self.config.get("vision.require_person_roi", False))
        if not require_roi:
            return True
        if not vision or not hasattr(vision, "person_in_roi"):
            self._logger.warning("ROI gating enabled but vision tentacle unavailable.")
            return False
        try:
            return bool(vision.person_in_roi())
        except Exception:
            self._logger.debug("ROI gating check failed.", exc_info=True)
            return False

    async def _handle_transcript(self, text: str) -> None:
        self._logger.info("Heard: %s", text)
        orchestrator = self._orchestrator
        brain = getattr(orchestrator, "get_tentacle", lambda name: None)("brain")
        vocal = getattr(orchestrator, "get_tentacle", lambda name: None)("vocal")
        if not brain or not vocal:
            self._logger.warning("Brain or vocal tentacle missing.")
            self._write_status(state="IDLE")
            return
        self._write_status(last_prompt=text, last_prompt_at=time.time(), state="LISTENING")
        response = await brain.generate(text)
        self._write_status(last_response=response, last_response_at=time.time())
        await vocal.speak(response)

    def _write_status(
        self,
        listening: bool | None = None,
        last_transcript: str | None = None,
        last_heard_at: float | None = None,
        last_prompt: str | None = None,
        last_prompt_at: float | None = None,
        thinking: bool | None = None,
        last_response: str | None = None,
        last_response_at: float | None = None,
        state: str | None = None,
    ) -> None:
        try:
            update_status(
                listening=listening,
                last_transcript=last_transcript,
                last_heard_at=last_heard_at,
                last_prompt=last_prompt,
                last_prompt_at=last_prompt_at,
                thinking=thinking,
                last_response=last_response,
                last_response_at=last_response_at,
                state=state,
            )
        except Exception:
            self._logger.debug("Failed to update ASR status", exc_info=True)

    def _cleanup_path(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except Exception:
            return

    def _cleanup_tmp_audio(self) -> None:
        for pattern in [
            "didier_mic_*.wav",
            "didier_mic_*.wav.txt",
            "didier_mic_*_mono.wav",
            "didier_mic_*_mono.wav.txt",
        ]:
            for path in self._tmp_dir.glob(pattern):
                self._cleanup_path(path)
