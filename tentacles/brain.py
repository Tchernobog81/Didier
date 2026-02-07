import asyncio
import logging
import time
from pathlib import Path
from typing import Any, Dict

import httpx

from core.memory import MemoryStore
from core.status import update_status
from tentacles.base import BaseTentacle


class Tentacle(BaseTentacle):
    name = "brain"

    def __init__(self, config, orchestrator: object) -> None:
        super().__init__(config, orchestrator)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._base_url = self.config.get("ollama.base_url", "http://localhost:11434")
        self._model = self.config.get("ollama.model", "llama3.2:latest")
        self._timeout = self.config.get("ollama.timeout_seconds", 120)
        self._num_predict = self.config.get("ollama.num_predict", 200)
        self._temperature = self.config.get("ollama.temperature", 0.6)
        self._system_prompt = self.config.get("personality.system_prompt", "").strip()
        self._catchphrases = self.config.get("personality.catchphrases", [])
        self._openclaw_workspace = self.config.get("openclaw.workspace", "")
        self._openclaw_files = self.config.get(
            "openclaw.bootstrap_files",
            ["AGENTS.md", "SOUL.md", "USER.md", "TOOLS.md"],
        )
        self._openclaw_prompt = self._load_openclaw_prompt()
        memory_path = self.config.get("memory.path", "data/memory.json")
        max_items = int(self.config.get("memory.max_items", 200))
        max_chars = int(self.config.get("memory.max_chars", 8000))
        self._memory = MemoryStore(memory_path, max_items=max_items, max_chars=max_chars)
        self._memory_lock = asyncio.Lock()

    def _load_openclaw_prompt(self) -> str:
        if not self._openclaw_workspace:
            return ""
        workspace = Path(self._openclaw_workspace).expanduser()
        if not workspace.exists():
            return ""
        sections = []
        for name in self._openclaw_files:
            path = workspace / name
            if not path.exists():
                continue
            content = path.read_text(encoding="utf-8").strip()
            if content:
                sections.append(f"### {name}\n{content}")
        return "\n\n".join(sections).strip()

    async def run(self) -> None:
        self._logger.info("Brain tentacle ready (model=%s).", self._model)
        await self.stop_event.wait()

    async def generate(self, prompt: str) -> str:
        update_status(
            thinking=True,
            state="THINKING",
            last_prompt=prompt,
            last_prompt_at=time.time(),
        )
        self._logger.info("Brain state: THINKING")
        async with self._memory_lock:
            memory_context = self._memory.render()
        parts = []
        if self._openclaw_prompt:
            parts.append(self._openclaw_prompt)
        if memory_context:
            parts.append(f"### MÉMOIRE PERSISTANTE\n{memory_context}")
        if self._system_prompt:
            parts.append(self._system_prompt)
        parts.append(f"User: {prompt}\nDidier:")
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
        url = f"{self._base_url}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            update_status(thinking=False, state="IDLE", error=str(exc))
            self._logger.warning("Brain state: IDLE (error)")
            raise
        response_text = str(data.get("response", "")).strip()
        async with self._memory_lock:
            self._memory.add("user", prompt)
            self._memory.add("assistant", response_text)
            if self._openclaw_workspace:
                path = Path(self._openclaw_workspace) / "MEMORY.md"
                self._memory.write_openclaw_memory(path)
        update_status(
            thinking=False,
            state="IDLE",
            last_response=response_text,
            last_response_at=time.time(),
        )
        self._logger.info("Brain state: IDLE")
        return response_text
