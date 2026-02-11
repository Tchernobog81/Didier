#!/usr/bin/env python3
import argparse
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StatBlock:
    label: str
    samples_ms: list[float]

    @property
    def count(self) -> int:
        return len(self.samples_ms)

    @property
    def mean(self) -> float:
        return statistics.mean(self.samples_ms) if self.samples_ms else 0.0

    @property
    def max(self) -> float:
        return max(self.samples_ms) if self.samples_ms else 0.0

    @property
    def min(self) -> float:
        return min(self.samples_ms) if self.samples_ms else 0.0

    @property
    def variance(self) -> float:
        return statistics.pvariance(self.samples_ms) if self.samples_ms else 0.0

    @property
    def stdev(self) -> float:
        return statistics.pstdev(self.samples_ms) if self.samples_ms else 0.0


def timed_request(url: str, method: str = "GET", payload: dict | None = None) -> float:
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()
    end = time.perf_counter()
    return (end - start) * 1000.0


def run_block(label: str, iterations: int, fn) -> StatBlock:
    samples = []
    for _ in range(iterations):
        samples.append(fn())
    return StatBlock(label=label, samples_ms=samples)


def print_block(block: StatBlock) -> None:
    print(
        f"{block.label}: n={block.count} "
        f"mean={block.mean:.2f}ms min={block.min:.2f}ms "
        f"max={block.max:.2f}ms var={block.variance:.2f} sd={block.stdev:.2f}"
    )


def write_html_report(path: Path, blocks: list[StatBlock], base_url: str, device_id: str) -> None:
    rows = []
    for block in blocks:
        rows.append(
            "<tr>"
            f"<td>{block.label}</td>"
            f"<td>{block.count}</td>"
            f"<td>{block.mean:.2f}</td>"
            f"<td>{block.min:.2f}</td>"
            f"<td>{block.max:.2f}</td>"
            f"<td>{block.variance:.2f}</td>"
            f"<td>{block.stdev:.2f}</td>"
            "</tr>"
        )
    html = f"""<!doctype html>
<html lang="fr">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Actuators Benchmark</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #f8fafc; color: #111827; }}
    h1 {{ margin: 0 0 12px; }}
    .meta {{ margin-bottom: 18px; color: #4b5563; }}
    table {{ border-collapse: collapse; width: 100%; background: white; }}
    th, td {{ border: 1px solid #e5e7eb; padding: 8px; text-align: left; font-size: 14px; }}
    th {{ background: #f1f5f9; }}
  </style>
</head>
<body>
  <h1>Actuators Performance Report</h1>
  <div class="meta">Base URL: {base_url} · Device: {device_id}</div>
  <table>
    <thead>
      <tr>
        <th>Endpoint</th>
        <th>N</th>
        <th>Mean (ms)</th>
        <th>Min (ms)</th>
        <th>Max (ms)</th>
        <th>Variance</th>
        <th>Std Dev</th>
      </tr>
    </thead>
    <tbody>
      {"".join(rows)}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Simple actuators endpoint benchmark")
    parser.add_argument("--base-url", default="http://127.0.0.1:5003")
    parser.add_argument("--device-id", default="yl_192_168_1_19")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--html-out", default="actuators_bench_report.html")
    parser.add_argument("--json-out", default="actuators_bench_report.json")
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    device_id = args.device_id
    n = max(1, args.iterations)

    get_actuators_url = f"{base}/actuators"
    get_status_url = f"{base}/actuators/{device_id}/status"
    post_command_url = f"{base}/actuators/{device_id}/command"

    try:
        blocks = [
            run_block(
                "GET /actuators",
                n,
                lambda: timed_request(get_actuators_url, method="GET"),
            ),
            run_block(
                "GET /actuators/{id}/status",
                n,
                lambda: timed_request(get_status_url, method="GET"),
            ),
            run_block(
                "POST /actuators/{id}/command",
                n,
                lambda: timed_request(
                    post_command_url,
                    method="POST",
                    payload={"action": "on", "params": {}},
                ),
            ),
        ]
    except urllib.error.HTTPError as exc:
        print(f"HTTP error during benchmark: {exc.code} {exc.reason}", file=sys.stderr)
        return 2
    except urllib.error.URLError as exc:
        print(f"Connection error during benchmark: {exc.reason}", file=sys.stderr)
        return 2

    print("Actuators benchmark")
    print(f"Base URL: {base}")
    print(f"Device ID: {device_id}")
    for block in blocks:
        print_block(block)

    data = {
        "base_url": base,
        "device_id": device_id,
        "iterations": n,
        "results": [
            {
                "label": b.label,
                "n": b.count,
                "mean_ms": b.mean,
                "min_ms": b.min,
                "max_ms": b.max,
                "variance": b.variance,
                "stddev": b.stdev,
                "samples_ms": b.samples_ms,
            }
            for b in blocks
        ],
    }

    json_path = Path(args.json_out)
    json_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    html_path = Path(args.html_out)
    write_html_report(html_path, blocks, base, device_id)
    print(f"JSON report: {json_path}")
    print(f"HTML report: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
