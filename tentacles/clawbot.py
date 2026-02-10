import asyncio
import json
import logging
import shutil
import time
from pathlib import Path
from typing import Any, Dict

import httpx

from core.memory import MemoryStore
from core.status import read_status, update_status
from tentacles.base import BaseTentacle


class Tentacle(BaseTentacle):
    name = "clawbot"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(f"Tentacle.{self.name}")
        self._enabled = bool(self.config.get("clawbot.enabled", False))
        self._interval = int(self.config.get("clawbot.interval_seconds", 300))
        self._report_path = Path(
            self.config.get("clawbot.report_path", "data/clawbot_report.json")
        )
        self._max_reports = int(self.config.get("clawbot.max_reports", 50))
        self._summary_max_chars = int(
            self.config.get("clawbot.summary_max_chars", 400)
        )
        self._write_memory = bool(self.config.get("clawbot.write_memory", True))
        self._base_url = self.config.get("ollama.base_url", "http://localhost:11434")
        self._model = self.config.get(
            "clawbot.model",
            self.config.get("coding.model", self.config.get("ollama.model")),
        )
        self._num_predict = int(
            self.config.get(
                "clawbot.num_predict",
                self.config.get("coding.num_predict", self.config.get("ollama.num_predict", 200)),
            )
        )
        self._temperature = float(
            self.config.get(
                "clawbot.temperature",
                self.config.get("coding.temperature", self.config.get("ollama.temperature", 0.4)),
            )
        )
        self._keep_alive = self.config.get("ollama.keep_alive", None)
        self._system_prompt = str(
            self.config.get(
                "clawbot.system_prompt",
                "Tu es Clawbot, un agent OpenClaw. Tu réponds en français, brièvement, et tu suis AGENTS/TOOLS/SOUL/USER.",
            )
        ).strip()
        self._memory_path = self.config.get("memory.path", "data/memory.json")
        self._memory_max_items = int(self.config.get("memory.max_items", 200))
        self._memory_max_chars = int(self.config.get("memory.max_chars", 8000))

    async def run(self) -> None:
        if not self._enabled:
            self._logger.warning("Clawbot tentacle disabled.")
            await self.stop_event.wait()
            return
        self._logger.info("Clawbot tentacle started (interval=%ss).", self._interval)
        while not self.stop_event.is_set():
            start = time.time()
            try:
                await self._run_veille()
            except Exception:
                self._logger.debug("Clawbot veille failed.", exc_info=True)
            elapsed = time.time() - start
            sleep_for = max(1.0, self._interval - elapsed)
            try:
                await asyncio.wait_for(self.stop_event.wait(), timeout=sleep_for)
            except asyncio.TimeoutError:
                continue

    async def _run_veille(self) -> dict[str, Any]:
        snapshot = self._build_snapshot()
        response = await self._ask_clawbot(snapshot)
        report = {
            "ts": time.time(),
            "snapshot": snapshot,
            "response": response,
        }
        self._append_report(report)
        summary = (response or "").strip().splitlines()[0:3]
        summary_text = " ".join(summary).strip()
        if len(summary_text) > self._summary_max_chars:
            summary_text = summary_text[: self._summary_max_chars].rstrip() + "…"
        update_status(
            clawbot_last_at=report["ts"],
            clawbot_last_summary=summary_text,
        )
        if self._write_memory and summary_text:
            memory = MemoryStore(
                self._memory_path,
                max_items=self._memory_max_items,
                max_chars=self._memory_max_chars,
            )
            memory.add("clawbot", f"Veille: {summary_text}")
            workspace = self.config.get("openclaw.workspace", "")
            if workspace:
                memory.write_openclaw_memory(Path(workspace) / "MEMORY.md")
        return report

    async def run_once(self) -> dict[str, Any]:
        return await self._run_veille()

    def _build_snapshot(self) -> Dict[str, Any]:
        status = read_status()
        root_path = Path("/host") if Path("/host").exists() else Path("/")
        ssd_mount = Path(self.config.get("storage.ssd_mount", "/mnt/didier_ssd"))
        root_usage = shutil.disk_usage(str(root_path))
        ssd_usage = None
        ssd_path = ssd_mount
        if not ssd_path.exists() and root_path != Path("/"):
            try:
                if ssd_mount.is_absolute():
                    ssd_path = root_path / ssd_mount.relative_to("/")
                else:
                    ssd_path = root_path / ssd_mount
            except Exception:
                ssd_path = ssd_mount
        if ssd_path.exists():
            ssd_usage = shutil.disk_usage(str(ssd_path))
        paths = {
            "asr_model": self.config.get("asr.model_path", ""),
            "asr_wake_model": self.config.get("asr.wake_model_path", ""),
            "tts_model": self.config.get("tts.model_path", ""),
            "tts_voices": self.config.get("tts.voices_path", ""),
            "vision_model": self.config.get("vision.model_path", ""),
            "vision_owner_model": self.config.get("vision.owner_embedding_model", ""),
        }
        path_exists = {k: bool(v) and Path(v).exists() for k, v in paths.items()}
        snapshot = {
            "ts": time.time(),
            "status": status,
            "disks": {
                "root": {
                    "path": str(root_path),
                    "total": root_usage.total,
                    "used": root_usage.used,
                    "free": root_usage.free,
                },
                "ssd": (
                    {
                        "path": str(ssd_path),
                        "total": ssd_usage.total,
                        "used": ssd_usage.used,
                        "free": ssd_usage.free,
                    }
                    if ssd_usage
                    else None
                ),
            },
            "paths": paths,
            "paths_ok": path_exists,
            "pulse_socket": Path("/run/user/1000/pulse/native").exists(),
            "wake_word": self.config.get("asr.wake_word", ""),
            "asr_model": Path(self.config.get("asr.model_path", "")).name,
            "asr_wake_model": Path(self.config.get("asr.wake_model_path", "")).name,
            "ollama_model": self.config.get("ollama.model", ""),
        }
        return snapshot

    async def _ask_clawbot(self, snapshot: Dict[str, Any]) -> str:
        parts = []
        if self._system_prompt:
            parts.append(self._system_prompt)
        parts.append(
            "Tu es en mode veille technique. Analyse le snapshot JSON. "
            "Donne: 1) diagnostic court, 2) alertes (ou RAS), 3) actions recommandées (1-3)."
        )
        parts.append(json.dumps(snapshot, ensure_ascii=False))
        full_prompt = "\n\n".join(parts)
        payload: Dict[str, Any] = {
            "model": self._model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "num_predict": self._num_predict,
                "temperature": self._temperature,
            },
        }
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        url = f"{self._base_url}/api/generate"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        return str(data.get("response", "")).strip()

    def _append_report(self, report: Dict[str, Any]) -> None:
        data: Dict[str, Any] = {"history": []}
        if self._report_path.exists():
            try:
                data = json.loads(self._report_path.read_text(encoding="utf-8"))
            except Exception:
                data = {"history": []}
        history = data.get("history", [])
        if not isinstance(history, list):
            history = []
        history.append(report)
        if len(history) > self._max_reports:
            history = history[-self._max_reports :]
        data["history"] = history
        self._report_path.parent.mkdir(parents=True, exist_ok=True)
        self._report_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
