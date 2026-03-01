#!/usr/bin/env python3
"""Measure Didier chat latency and response/audio compactness from /ask-and-speak."""

from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    rank = max(0.0, min(1.0, p)) * (len(values) - 1)
    low = int(rank)
    high = min(low + 1, len(values) - 1)
    frac = rank - low
    return float(values[low] * (1.0 - frac) + values[high] * frac)


def _post_json(url: str, payload: dict[str, Any], timeout_s: float) -> tuple[dict[str, Any], int]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        status = int(getattr(response, "status", 200) or 200)
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        data = {"response": str(data)}
    return data, status


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def measure(url: str, prompts: list[str], iterations: int, timeout_s: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx in range(iterations):
        prompt = prompts[idx % len(prompts)]
        payload = {
            "prompt": prompt,
            "source": "measure_chat_latency",
            "is_voice": False,
            "force_task": False,
            "vision_glance": False,
            "boost": False,
        }
        started = time.perf_counter()
        status = 0
        data: dict[str, Any] = {}
        error = ""
        try:
            data, status = _post_json(url, payload, timeout_s=timeout_s)
        except urllib.error.HTTPError as exc:
            status = int(getattr(exc, "code", 0) or 0)
            error = f"http_error:{status}"
        except Exception as exc:
            error = f"{type(exc).__name__}:{exc}"
        elapsed_ms = int(max(0.0, (time.perf_counter() - started) * 1000))
        response_text = str(data.get("response", "")).strip()
        diagnostics = data.get("diagnostics", {}) if isinstance(data.get("diagnostics"), dict) else {}
        response_diag = diagnostics.get("response", {}) if isinstance(diagnostics.get("response"), dict) else {}
        tts_diag = diagnostics.get("tts", {}) if isinstance(diagnostics.get("tts"), dict) else {}
        row = {
            "idx": idx + 1,
            "prompt": prompt,
            "status": status,
            "error": error,
            "client_ms": elapsed_ms,
            "server_ms": _safe_int(data.get("server_elapsed_ms")),
            "route": str(data.get("route", "")).strip() or str(
                ((data.get("routing") or {}).get("execution_backend", ""))
            ).strip(),
            "audio_status": str(data.get("audio_status", "")).strip(),
            "response_chars": _safe_int(response_diag.get("chars", len(response_text))),
            "response_sentences": _safe_int(response_diag.get("sentences")),
            "tts_chars": _safe_int(tts_diag.get("chars")),
            "tts_sentences": _safe_int(tts_diag.get("sentences")),
            "audio_queue_ms": _safe_int(diagnostics.get("audio_queue_ms")),
        }
        rows.append(row)
    return rows


def print_summary(rows: list[dict[str, Any]]) -> None:
    ok_rows = [row for row in rows if not row.get("error") and int(row.get("status", 0)) < 400]
    print(f"samples={len(rows)} ok={len(ok_rows)} errors={len(rows) - len(ok_rows)}")
    if not ok_rows:
        return
    client = sorted(float(row.get("client_ms", 0) or 0) for row in ok_rows)
    server = sorted(float(row.get("server_ms", 0) or 0) for row in ok_rows)
    resp_chars = sorted(float(row.get("response_chars", 0) or 0) for row in ok_rows)
    tts_chars = sorted(float(row.get("tts_chars", 0) or 0) for row in ok_rows)
    queue_ms = sorted(float(row.get("audio_queue_ms", 0) or 0) for row in ok_rows)
    print(
        "client_ms min={:.0f} p50={:.0f} p95={:.0f} max={:.0f}".format(
            min(client), _percentile(client, 0.5), _percentile(client, 0.95), max(client)
        )
    )
    print(
        "server_ms min={:.0f} p50={:.0f} p95={:.0f} max={:.0f}".format(
            min(server), _percentile(server, 0.5), _percentile(server, 0.95), max(server)
        )
    )
    print(
        "resp_chars avg={:.1f} p50={:.0f} p95={:.0f}".format(
            statistics.mean(resp_chars), _percentile(resp_chars, 0.5), _percentile(resp_chars, 0.95)
        )
    )
    print(
        "tts_chars avg={:.1f} p50={:.0f} p95={:.0f}".format(
            statistics.mean(tts_chars), _percentile(tts_chars, 0.5), _percentile(tts_chars, 0.95)
        )
    )
    print(
        "audio_queue_ms avg={:.1f} p95={:.0f}".format(
            statistics.mean(queue_ms), _percentile(queue_ms, 0.95)
        )
    )


def write_jsonl(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:5003/ask-and-speak",
        help="Target ask-and-speak URL.",
    )
    parser.add_argument(
        "--prompt",
        action="append",
        default=[],
        help="Prompt to send (repeat --prompt for multiple).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=12,
        help="Number of requests to run.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--out",
        default="logs/chat_latency_measurements.jsonl",
        help="Output JSONL path.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    prompts = [p.strip() for p in args.prompt if str(p).strip()]
    if not prompts:
        prompts = [
            "Salut! Tu es quel modele ?",
            "Resume ton etat en une phrase.",
            "Quelle route utilises-tu pour me repondre ?",
        ]
    rows = measure(
        url=str(args.url).strip(),
        prompts=prompts,
        iterations=max(1, int(args.iterations)),
        timeout_s=max(0.5, float(args.timeout)),
    )
    output_path = Path(str(args.out))
    write_jsonl(rows, output_path)
    print_summary(rows)
    print(f"saved={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
