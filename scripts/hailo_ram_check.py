#!/usr/bin/env python3
"""Simple RAM availability checker for Edge AI rollout safety."""

from __future__ import annotations

import argparse
import sys


def read_meminfo_kib() -> dict[str, int]:
    values: dict[str, int] = {}
    with open("/proc/meminfo", "r", encoding="utf-8") as handle:
        for line in handle:
            if ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            parts = raw_value.strip().split()
            if not parts:
                continue
            try:
                values[key] = int(parts[0])
            except ValueError:
                continue
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Check available RAM in MiB.")
    parser.add_argument(
        "--min-mib",
        type=int,
        default=1024,
        help="Minimum required available RAM in MiB (default: 1024)",
    )
    args = parser.parse_args()

    data = read_meminfo_kib()
    total_mib = data.get("MemTotal", 0) / 1024.0
    avail_mib = data.get("MemAvailable", 0) / 1024.0

    print(f"RAM total: {total_mib:.1f} MiB")
    print(f"RAM available: {avail_mib:.1f} MiB")
    print(f"Threshold: {args.min_mib} MiB")

    if avail_mib >= args.min_mib:
        print("RAM check: OK")
        return 0

    print("RAM check: LOW")
    return 1


if __name__ == "__main__":
    sys.exit(main())

