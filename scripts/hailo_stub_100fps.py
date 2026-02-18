#!/usr/bin/env python3
"""Stub throughput simulator for 100 FPS scheduling tests.

Official invocation:
python3 -m scripts.hailo_stub_100fps --seconds 2 --fps 100
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import argparse
import time

from core.hailo.detector import build_backend


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Simulate a fixed-FPS loop against the stub vision backend."
    )
    parser.add_argument("--seconds", type=float, default=5.0, help="Run duration.")
    parser.add_argument("--fps", type=float, default=100.0, help="Target FPS.")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if achieved FPS < 90% of target.",
    )
    args = parser.parse_args()

    duration = max(0.5, float(args.seconds))
    target_fps = max(1.0, float(args.fps))
    period = 1.0 / target_fps
    frame = b"\x00" * (640 * 480 * 3)

    backend = build_backend(cpu_detect_fn=lambda _frame: [])
    started = time.perf_counter()
    deadline = started + duration
    next_tick = started
    loops = 0

    while True:
        now = time.perf_counter()
        if now >= deadline:
            break
        backend.detect(frame)
        loops += 1
        next_tick += period
        sleep_time = next_tick - time.perf_counter()
        if sleep_time > 0:
            time.sleep(sleep_time)

    elapsed = max(0.001, time.perf_counter() - started)
    achieved_fps = loops / elapsed
    target_min = target_fps * 0.90

    print(f"mode: {backend.status().get('mode')}")
    print(f"target_fps: {target_fps:.2f}")
    print(f"achieved_fps: {achieved_fps:.2f}")
    print(f"frames: {loops}")
    print(f"elapsed_s: {elapsed:.3f}")

    if achieved_fps >= target_min:
        print("stub throughput: OK")
        return 0

    print("stub throughput: BELOW_TARGET")
    return 1 if args.strict else 0


if __name__ == "__main__":
    # Keep this entrypoint; official usage remains module mode via `python3 -m ...`.
    raise SystemExit(main())
