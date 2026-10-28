#!/usr/bin/env bash
# Restart the API with the given number of server processes, ramp the load up with k6, and add
# latency over time and peak CPU use to the GitHub job summary.
#
#   loadtest/stress.sh 4

set -euo pipefail

WORKERS=$1
SUMMARY=${GITHUB_STEP_SUMMARY:-/dev/stdout}

API_WORKERS=$WORKERS docker compose up --detach --wait api

# Sample CPU use while k6 runs. A single snapshot afterwards says nothing about the peak.
docker stats --format '{{.Name}} {{.CPUPerc}}' > loadtest/cpu.txt &
SAMPLER=$!

# Thresholds are expected to break under stress, so that doesn't fail the step.
k6 run -e PROFILE=stress --out csv=loadtest/results.csv loadtest/api.js > /dev/null || true

kill "$SAMPLER"
PEAK_CPU=$(python3 - <<'PY'
import re
peak = 0.0
for line in open("loadtest/cpu.txt", errors="ignore"):
    match = re.search(r"signalfloor-api-1\s+([\d.]+)%", line)
    if match:
        peak = max(peak, float(match.group(1)))
print(f"{peak:.0f}%")
PY
)

{
  echo "## Stress with $WORKERS server process(es)"
  echo
  echo "Peak CPU of the API container: $PEAK_CPU, out of $(nproc) cores ($(nproc)00%)."
  echo
  python3 loadtest/report.py loadtest/results.csv
  echo
} | tee -a "$SUMMARY"
