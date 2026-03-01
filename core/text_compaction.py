"""Utilities for response length control and lightweight text metrics."""

from __future__ import annotations

import re

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences(text: str) -> list[str]:
    raw = str(text or "").strip()
    if not raw:
        return []
    chunks = [part.strip() for part in _SENTENCE_SPLIT_RE.split(raw) if part.strip()]
    return chunks or [raw]


def text_stats(text: str) -> dict[str, int]:
    raw = str(text or "").strip()
    if not raw:
        return {"chars": 0, "words": 0, "sentences": 0}
    words = len([tok for tok in re.findall(r"\S+", raw) if tok])
    sentences = len(split_sentences(raw))
    return {
        "chars": len(raw),
        "words": max(0, words),
        "sentences": max(0, sentences),
    }


def compact_text(
    text: str,
    *,
    max_sentences: int,
    max_chars: int,
) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    bounded_sentences = max(1, int(max_sentences or 1))
    bounded_chars = max(20, int(max_chars or 20))
    chunks = split_sentences(raw)
    compact = " ".join(chunks[:bounded_sentences]).strip() if chunks else raw
    if len(compact) <= bounded_chars:
        return compact
    clipped = compact[:bounded_chars].rstrip()
    if " " in clipped:
        clipped = clipped.rsplit(" ", 1)[0]
    clipped = clipped.rstrip(" ,;:")
    if not clipped:
        return compact[:bounded_chars].strip()
    if clipped[-1] not in ".!?":
        clipped = f"{clipped}."
    return clipped
