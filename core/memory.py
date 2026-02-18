import json
import threading
import time
from typing import Any, Iterable


class MemoryStore:
    def __init__(self, path: str, max_items: int = 200, max_chars: int = 8000) -> None:
        self._path = Path(path)
        self._max_items = max_items
        self._max_chars = max_chars
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._entries = []
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                self._entries = data
            else:
                self._entries = []
        except Exception:
            self._entries = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(self._entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, role: str, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        entry = {"ts": time.time(), "role": role, "text": text}
        with self._lock:
            self._entries.append(entry)
            self._compact_if_needed()
            self._save()

    def _compact_if_needed(self) -> None:
        if len(self._entries) <= self._max_items:
            return
        keep_last = max(40, self._max_items // 3)
        old_entries = self._entries[:-keep_last]
        recent_entries = self._entries[-keep_last:]
        compact_lines = []
        for entry in old_entries:
            role = entry.get("role", "?")
            text = entry.get("text", "")
            if text:
                compact_lines.append(f"- [{role}] {text}")
        compact_text = "\n".join(compact_lines)
        if len(compact_text) > self._max_chars:
            compact_text = compact_text[: self._max_chars].rstrip() + "…"
        summary_entry = {
            "ts": time.time(),
            "role": "memo",
            "text": "Mémoire compacte (résumé brut) :\n" + compact_text,
        }
        self._entries = [summary_entry] + recent_entries

    def render(self, max_chars: int | None = None, max_items: int | None = None) -> str:
        limit_chars = max_chars or self._max_chars
        limit_items = max_items or self._max_items
        with self._lock:
            entries = self._entries[-limit_items:]
        lines: list[str] = []
        total = 0
        for entry in entries:
            line = f"[{entry.get('role','?')}] {entry.get('text','')}".strip()
            if not line:
                continue
            if total + len(line) + 1 > limit_chars:
                break
            lines.append(line)
            total += len(line) + 1
        return "\n".join(lines).strip()
