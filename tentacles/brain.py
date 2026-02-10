import asyncio
import csv
import json
import logging
import os
import re
import threading
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
        self._logger = logging.getLogger(f"Tentacle.{self.name}")
        self._base_url = self.config.get("ollama.base_url", "http://localhost:11434")
        self._model = self.config.get("ollama.model", "llama3.2:latest")
        self._timeout = self.config.get("ollama.timeout_seconds", 120)
        self._num_predict = self.config.get("ollama.num_predict", 200)
        self._temperature = self.config.get("ollama.temperature", 0.6)
        self._keep_alive = self.config.get("ollama.keep_alive", None)
        self._autotune_enabled = bool(
            self.config.get("ollama.autotune_enabled", False)
        )
        self._autotune_interval = int(
            self.config.get("ollama.autotune_interval_seconds", 1800)
        )
        self._autotune_cooldown = int(
            self.config.get("ollama.autotune_cooldown_seconds", 1800)
        )
        self._autotune_prompt = str(
            self.config.get(
                "ollama.autotune_prompt",
                "Réponds en une phrase courte: Bonjour.",
            )
        )
        self._autotune_num_predict = int(
            self.config.get("ollama.autotune_num_predict", 128)
        )
        self._autotune_temperature = float(
            self.config.get("ollama.autotune_temperature", 0.2)
        )
        self._autotune_timeout = int(
            self.config.get("ollama.autotune_timeout_seconds", 60)
        )
        self._autotune_models = self.config.get("ollama.autotune_models", []) or []
        self._autotune_bench_output = str(
            self.config.get("ollama.autotune_bench_output", "logs/bench_llm.csv")
        )
        self._autotune_min_b = float(
            self.config.get("ollama.autotune_min_b", 3.0)
        )
        self._autotune_tps_target = float(
            self.config.get("ollama.autotune_tps_target", 8.0)
        )
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
        self._model_lock = threading.Lock()
        self._autotune_thread: threading.Thread | None = None
        self._autotune_stop = threading.Event()
        self._autotune_last_run = 0.0
        self._autotune_last_switch = 0.0
        self._busy = False

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

    async def generate(
        self,
        prompt: str,
        model_override: str | None = None,
        system_override: str | None = None,
    ) -> str:
        self._busy = True
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
        if system_override:
            parts.append(system_override)
        parts.append(f"User: {prompt}\nDidier:")
        full_prompt = "\n\n".join(parts)
        with self._model_lock:
            model = model_override or self._model
            num_predict = self._num_predict
            temperature = self._temperature
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": full_prompt,
            "stream": False,
            "options": {
                "num_predict": num_predict,
                "temperature": temperature,
            },
        }
        if self._keep_alive:
            payload["keep_alive"] = self._keep_alive
        url = f"{self._base_url}/api/generate"
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            update_status(thinking=False, state="IDLE", error=str(exc))
            self._logger.warning("Brain state: IDLE (error)")
            self._busy = False
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
        self._busy = False
        return response_text

    async def start(self) -> None:
        if self._autotune_enabled:
            self._start_autotune_thread()
        await super().start()

    async def stop(self) -> None:
        self._autotune_stop.set()
        if self._autotune_thread and self._autotune_thread.is_alive():
            self._autotune_thread.join(timeout=2)
        await super().stop()

    def _start_autotune_thread(self) -> None:
        if self._autotune_thread and self._autotune_thread.is_alive():
            return
        self._autotune_last_run = time.time()
        self._autotune_thread = threading.Thread(
            target=self._autotune_loop, daemon=True
        )
        self._autotune_thread.start()

    def _autotune_loop(self) -> None:
        try:
            os.nice(10)
        except Exception:
            pass
        time.sleep(3.0)
        while not self._autotune_stop.is_set():
            now = time.time()
            if self._busy:
                time.sleep(1.0)
                continue
            if now - self._autotune_last_run < self._autotune_interval:
                time.sleep(1.0)
                continue
            self._autotune_last_run = now
            try:
                self._run_bench()
                choice = self._select_best_model()
                if choice:
                    with self._model_lock:
                        if choice != self._model and (
                            now - self._autotune_last_switch
                            >= self._autotune_cooldown
                        ):
                            self._model = choice
                            self._autotune_last_switch = now
                            self._persist_model(choice)
                            update_status(
                                llm_model_selected=choice,
                                llm_model_selected_at=now,
                            )
            except Exception:
                self._logger.debug("LLM autotune loop error.", exc_info=True)

    def _run_bench(self) -> None:
        models = self._list_models()
        if not models:
            return
        output = Path(self._autotune_bench_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        write_header = not output.exists()
        with output.open("a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(
                    [
                        "ts",
                        "model",
                        "elapsed_ms",
                        "tps",
                        "eval_count",
                        "eval_ms",
                        "prompt_eval_count",
                        "prompt_eval_ms",
                    ]
                )
            for model in models:
                data, elapsed_ms = self._bench_model(model)
                if not data:
                    continue
                tps = self._compute_tps(data, elapsed_ms)
                writer.writerow(
                    [
                        int(time.time()),
                        model,
                        elapsed_ms,
                        f"{tps:.3f}",
                        int(data.get("eval_count") or 0),
                        int((data.get("eval_duration") or 0) / 1e6),
                        int(data.get("prompt_eval_count") or 0),
                        int((data.get("prompt_eval_duration") or 0) / 1e6),
                    ]
                )
                update_status(
                    llm_bench_last_ms=elapsed_ms,
                    llm_bench_model=model,
                )

    def _bench_model(self, model: str) -> tuple[dict[str, Any], int] | None:
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": self._autotune_prompt,
            "stream": False,
            "options": {
                "num_predict": self._autotune_num_predict,
                "temperature": self._autotune_temperature,
            },
        }
        url = f"{self._base_url}/api/generate"
        start = time.time()
        try:
            resp = httpx.post(url, json=payload, timeout=self._autotune_timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            self._logger.debug("Bench failed for %s", model, exc_info=True)
            return None
        elapsed_ms = int((time.time() - start) * 1000)
        return data, elapsed_ms

    def _compute_tps(self, data: dict[str, Any], elapsed_ms: int) -> float:
        eval_count = data.get("eval_count")
        eval_duration = data.get("eval_duration")
        if eval_count and eval_duration:
            seconds = float(eval_duration) / 1e9
            return float(eval_count) / max(seconds, 1e-6)
        response = str(data.get("response") or "")
        tokens = max(1, len(response.split()))
        return tokens / max(elapsed_ms / 1000.0, 1e-3)

    def _list_models(self) -> list[str]:
        models: list[str] = []
        try:
            resp = httpx.get(f"{self._base_url}/api/tags", timeout=10)
            resp.raise_for_status()
            payload = resp.json()
            for item in payload.get("models", []):
                name = item.get("name") or item.get("model")
                if name:
                    models.append(str(name))
        except Exception:
            self._logger.debug("Failed to list Ollama models.", exc_info=True)
            return []
        if self._autotune_models:
            allow = {str(m) for m in self._autotune_models}
            models = [m for m in models if m in allow]
        return models

    def _select_best_model(self) -> str | None:
        bench_path = Path(self._autotune_bench_output)
        if not bench_path.exists():
            return None
        latest: dict[str, tuple[float, float]] = {}
        try:
            with bench_path.open("r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    model = str(row.get("model", "")).strip()
                    if not model:
                        continue
                    try:
                        tps = float(row.get("tps", "0"))
                    except ValueError:
                        continue
                    try:
                        ts = float(row.get("ts", "0"))
                    except ValueError:
                        ts = 0.0
                    prev = latest.get(model)
                    if prev is None or ts >= prev[1]:
                        latest[model] = (tps, ts)
        except Exception:
            self._logger.debug("Failed to parse LLM bench results.", exc_info=True)
            return None

        if not latest:
            return None

        candidates = []
        for model, (tps, _ts) in latest.items():
            size_b = self._model_size_b(model)
            if size_b < self._autotune_min_b:
                continue
            candidates.append((model, tps, size_b))

        if not candidates:
            return None

        within = [c for c in candidates if c[1] >= self._autotune_tps_target]
        if within:
            within.sort(key=lambda x: (-x[2], -x[1]))
            return within[0][0]

        candidates.sort(key=lambda x: (-x[1], -x[2]))
        return candidates[0][0]

    def _model_size_b(self, model: str) -> float:
        match = re.search(r"(\d+(?:\.\d+)?)b", model.lower())
        if not match:
            return 0.0
        try:
            return float(match.group(1))
        except ValueError:
            return 0.0

    def _persist_model(self, model: str) -> None:
        try:
            path = self.config.source_path
            data = json.loads(path.read_text(encoding="utf-8"))
            ollama = data.get("ollama", {})
            ollama["model"] = model
            ollama["model_selected_at"] = time.time()
            data["ollama"] = ollama
            path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception:
            self._logger.debug("Failed to persist LLM model.", exc_info=True)
