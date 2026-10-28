"""Turn a k6 CSV export into a table of latency over time, per scenario.

    python3 loadtest/report.py loadtest/results.csv

k6's own summary gives one number per scenario for the whole run. Under a ramp that hides the
moment things went wrong, so this splits the run into windows instead.
"""

from __future__ import annotations

import csv
import sys
from collections import defaultdict

WINDOW_SECONDS = 15


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(p / 100 * len(ordered)))]


def main(path: str) -> None:
    durations: dict[tuple[int, str], list[float]] = defaultdict(list)
    failures: dict[tuple[int, str], int] = defaultdict(int)
    start: int | None = None

    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            if row["metric_name"] not in ("http_req_duration", "http_req_failed"):
                continue
            scenario = row.get("scenario", "")
            if not scenario:
                continue
            second = int(row["timestamp"])
            start = second if start is None else min(start, second)
            key = ((second - start) // WINDOW_SECONDS, scenario)
            if row["metric_name"] == "http_req_duration":
                durations[key].append(float(row["metric_value"]))
            elif float(row["metric_value"]) > 0:
                failures[key] += 1

    scenarios = sorted({s for _, s in durations})
    windows = sorted({w for w, _ in durations})
    print("| Seconds | " + " | ".join(scenarios) + " |")
    print("|---|" + "---|" * len(scenarios))
    for w in windows:
        cells = []
        for s in scenarios:
            values = durations.get((w, s), [])
            if not values:
                cells.append("")
                continue
            rate = len(values) / WINDOW_SECONDS
            failed = failures.get((w, s), 0) / len(values) * 100
            p50, p95 = percentile(values, 50), percentile(values, 95)
            cell = f"{rate:.0f}/s, p50 {p50:.0f} ms, p95 {p95:.0f} ms"
            if failed:
                cell += f", {failed:.0f}% failed"
            cells.append(cell)
        first = w * WINDOW_SECONDS
        print(f"| {first}-{first + WINDOW_SECONDS} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main(sys.argv[1])
