#!/usr/bin/env python3
"""Validate the final chat E2E path: written prompt, visible thinking, written response, audio queued."""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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


def _get_json(url: str, timeout_s: float) -> tuple[dict[str, Any], int]:
    req = urllib.request.Request(
        url=url,
        method="GET",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as response:
        status = int(getattr(response, "status", 200) or 200)
        raw = response.read().decode("utf-8", errors="replace")
    data = json.loads(raw) if raw.strip() else {}
    if not isinstance(data, dict):
        data = {}
    return data, status


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _default_prompt() -> str:
    return "Explique en une phrase concise comment tu choisis ta route de reponse."


def run_validation(
    *,
    ask_url: str,
    status_url: str,
    prompt: str,
    timeout_s: float,
    poll_interval_s: float,
    require_audio: bool,
    require_thinking: bool,
) -> dict[str, Any]:
    payload = {
        "prompt": str(prompt).strip(),
        "source": "validate_chat_e2e",
        "is_voice": False,
        "force_task": False,
        "vision_glance": False,
        "boost": False,
    }
    result: dict[str, Any] = {
        "prompt": payload["prompt"],
        "ask_url": ask_url,
        "status_url": status_url,
        "started_at": time.time(),
        "thinking_seen": False,
        "thinking_samples": 0,
        "status_http_errors": [],
        "status_http_codes": [],
        "failures": [],
    }
    request_state: dict[str, Any] = {
        "done": False,
        "status": 0,
        "data": {},
        "error": "",
        "started": time.perf_counter(),
        "ended": 0.0,
    }

    def _request_thread() -> None:
        try:
            data, status = _post_json(ask_url, payload, timeout_s=timeout_s)
            request_state["data"] = data
            request_state["status"] = status
        except urllib.error.HTTPError as exc:
            request_state["status"] = int(getattr(exc, "code", 0) or 0)
            request_state["error"] = f"http_error:{request_state['status']}"
        except Exception as exc:
            request_state["error"] = f"{type(exc).__name__}:{exc}"
        finally:
            request_state["ended"] = time.perf_counter()
            request_state["done"] = True

    worker = threading.Thread(target=_request_thread, daemon=True)
    worker.start()

    deadline = time.perf_counter() + float(timeout_s)
    while worker.is_alive() and time.perf_counter() < deadline:
        try:
            status_data, status_code = _get_json(status_url, timeout_s=min(1.0, timeout_s))
            result["status_http_codes"].append(int(status_code))
            result["thinking_samples"] += 1
            if bool(status_data.get("thinking")) or str(status_data.get("state", "")).upper() == "THINKING":
                result["thinking_seen"] = True
        except Exception as exc:
            result["status_http_errors"].append(f"{type(exc).__name__}:{exc}")
        time.sleep(max(0.02, float(poll_interval_s)))

    worker.join(timeout=max(0.0, deadline - time.perf_counter()))

    elapsed_ms = int(max(0.0, (request_state["ended"] - request_state["started"]) * 1000))
    data = request_state.get("data", {}) if isinstance(request_state.get("data"), dict) else {}
    diagnostics = data.get("diagnostics", {}) if isinstance(data.get("diagnostics"), dict) else {}
    response_diag = diagnostics.get("response", {}) if isinstance(diagnostics.get("response"), dict) else {}
    result.update(
        {
            "completed_at": time.time(),
            "client_ms": elapsed_ms,
            "ask_http_status": int(request_state.get("status", 0) or 0),
            "request_error": str(request_state.get("error", "")).strip(),
            "server_ms": _safe_int(data.get("server_elapsed_ms")),
            "route": str(data.get("route", "")).strip()
            or str(((data.get("routing") or {}).get("execution_backend", ""))).strip(),
            "response": str(data.get("response", "")).strip(),
            "response_chars": _safe_int(response_diag.get("chars", len(str(data.get("response", "")).strip()))),
            "audio": bool(data.get("audio", False)),
            "audio_status": str(data.get("audio_status", "")).strip(),
            "audio_detail": str(data.get("audio_detail", "")).strip(),
            "raw": data,
        }
    )

    if result["request_error"]:
        result["failures"].append(result["request_error"])
    if int(result["ask_http_status"]) >= 400:
        result["failures"].append(f"http_status:{result['ask_http_status']}")
    if not result["response"]:
        result["failures"].append("missing_response")
    if _safe_int(result["response_chars"]) <= 0:
        result["failures"].append("missing_response_metrics")
    if require_thinking and not bool(result["thinking_seen"]):
        result["failures"].append("thinking_not_observed")
    if require_audio and not bool(result["audio"]):
        result["failures"].append(f"audio_not_queued:{result['audio_status'] or 'unknown'}")

    result["ok"] = not result["failures"]
    return result


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ask-url",
        default="http://127.0.0.1:5010/ask-and-speak",
        help="Target ask-and-speak URL.",
    )
    parser.add_argument(
        "--status-url",
        default="http://127.0.0.1:5010/asr/status",
        help="Target runtime status URL used to observe THINKING state.",
    )
    parser.add_argument(
        "--prompt",
        default=_default_prompt(),
        help="Prompt used to exercise the conversational path.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=12.0,
        help="HTTP timeout in seconds.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.05,
        help="Polling interval for the status endpoint in seconds.",
    )
    parser.add_argument(
        "--allow-missing-audio",
        action="store_true",
        help="Do not fail when audio is not queued.",
    )
    parser.add_argument(
        "--allow-missing-thinking",
        action="store_true",
        help="Do not fail when THINKING is not observed during the request.",
    )
    parser.add_argument(
        "--out",
        default="logs/chat_e2e_validation.json",
        help="Output JSON report path.",
    )
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    report = run_validation(
        ask_url=str(args.ask_url).strip(),
        status_url=str(args.status_url).strip(),
        prompt=str(args.prompt).strip() or _default_prompt(),
        timeout_s=max(0.5, float(args.timeout)),
        poll_interval_s=max(0.02, float(args.poll_interval)),
        require_audio=not bool(args.allow_missing_audio),
        require_thinking=not bool(args.allow_missing_thinking),
    )
    out_path = Path(str(args.out))
    write_report(out_path, report)
    print(f"ok={report['ok']} status={report['ask_http_status']} client_ms={report['client_ms']}")
    print(f"thinking_seen={report['thinking_seen']} audio={report['audio']} audio_status={report['audio_status']}")
    if report["failures"]:
        print("failures=" + ",".join(str(item) for item in report["failures"]))
    print(f"saved={out_path}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
