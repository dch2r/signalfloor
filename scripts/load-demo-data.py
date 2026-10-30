"""Upload the reference agent's real results to a running server, so the dashboard has data.

    python3 scripts/load-demo-data.py
    python3 scripts/load-demo-data.py --api http://localhost:8000

Uses only the standard library, so it runs without installing anything. Set
SIGNALFLOOR_API_KEY if the server requires a key. Each run is uploaded as a new run, so
running it twice gives two copies.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

RESULTS = Path(__file__).resolve().parents[1] / "packages/agent/results"

# File, run name and labels. The three v1 runs are identical reruns, which is what makes the
# noise band and the flaky cases visible.
RUNS = [
    ("v1-run1.jsonl", "prompt v1, run 1", {"prompt": "v1", "run": "1"}),
    ("v1-run2.jsonl", "prompt v1, run 2", {"prompt": "v1", "run": "2"}),
    ("v1-run3.jsonl", "prompt v1, run 3", {"prompt": "v1", "run": "3"}),
    ("v2-run1.jsonl", "prompt v2", {"prompt": "v2", "run": "1"}),
]


def upload(api: str, key: str | None, name: str, labels: dict[str, str], path: Path) -> str:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    body = {
        "name": name,
        "labels": {"demo": "yes", "model": "qwen3:1.7b", **labels},
        "cases": [{"id": row["id"], "score": row["score"]} for row in rows],
    }
    headers = {"content-type": "application/json"}
    if key:
        headers["authorization"] = f"Bearer {key}"
    request = urllib.request.Request(
        f"{api}/runs", data=json.dumps(body).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        run_id: str = json.load(response)["id"]
    return run_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://localhost:8000", help="the server's address")
    parser.add_argument("--dashboard", default="http://localhost:3000", help="for the link")
    args = parser.parse_args()
    key = os.environ.get("SIGNALFLOOR_API_KEY") or None

    ids = {}
    try:
        for file, name, labels in RUNS:
            ids[file] = upload(args.api, key, name, labels, RESULTS / file)
            print(f"uploaded {name}: {ids[file]}")
    except urllib.error.HTTPError as e:
        print(f"error: the server answered {e.code}: {e.read().decode()[:200]}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"error: can't reach {args.api} ({e.reason}). Is it running?", file=sys.stderr)
        return 1

    baseline, candidate = ids["v1-run1.jsonl"], ids["v2-run1.jsonl"]
    print(f"\nopen {args.dashboard}/compare?baseline={baseline}&candidate={candidate}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
