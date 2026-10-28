#!/usr/bin/env bash
# Check a running signalfloor stack end to end: upload two runs, compare them, run a background
# job through the worker, send a trace, and load the dashboard. Used against docker compose and
# against Kubernetes in CI.
#
#   scripts/smoke-test.sh [api url] [dashboard url]

set -euo pipefail

API=${1:-http://localhost:8000}
DASHBOARD=${2:-http://localhost:3000}

fail() { echo "FAIL: $*" >&2; exit 1; }
json() { python3 -c "import json, sys; print(json.load(sys.stdin)$1)"; }

wait_for() {
  for _ in $(seq 60); do
    curl -fs -o /dev/null "$1" && return 0
    sleep 2
  done
  fail "$1 never answered"
}

wait_for "$API/health/ready"
wait_for "$DASHBOARD"
echo "ok: API and dashboard are up"

cases() {
  python3 -c "
import json, sys
scores = [float(x) for x in sys.argv[1:]]
print(json.dumps([{'id': f'q{i}', 'score': s} for i, s in enumerate(scores)]))" "$@"
}
upload() {
  curl -fsS -X POST "$API/runs" -H 'content-type: application/json' \
    -d "{\"name\": \"$1\", \"labels\": {\"smoke\": \"yes\"}, \"cases\": $2}" | json "['id']"
}
BASELINE=$(upload "smoke baseline" "$(cases $(for _ in $(seq 40); do echo 1; done) $(for _ in $(seq 40); do echo 0; done))")
CANDIDATE=$(upload "smoke candidate" "$(cases $(for _ in $(seq 10); do echo 1; done) $(for _ in $(seq 70); do echo 0; done))")
echo "ok: uploaded runs $BASELINE and $CANDIDATE"

VERDICT=$(curl -fsS "$API/runs/$BASELINE/compare/$CANDIDATE?seed=0" | json "['verdict']")
[ "$VERDICT" = regression ] || fail "expected a regression, got $VERDICT"
echo "ok: compare says regression"

JOB=$(curl -fsS -X POST "$API/jobs/compare" -H 'content-type: application/json' \
  -d "{\"baseline_id\": \"$BASELINE\", \"candidate_id\": \"$CANDIDATE\", \"n_resamples\": 1000}" \
  | json "['id']")
for _ in $(seq 30); do
  STATUS=$(curl -fsS "$API/jobs/$JOB" | json "['status']")
  [ "$STATUS" = succeeded ] && break
  [ "$STATUS" = failed ] && fail "job $JOB failed"
  sleep 1
done
[ "$STATUS" = succeeded ] || fail "job $JOB still $STATUS, is the worker running?"
echo "ok: the worker ran a compare job"

TRACE=$(python3 -c "import secrets; print(secrets.token_hex(16))")
curl -fsS -o /dev/null -X POST "$API/v1/traces" -H 'content-type: application/json' -d "{
  \"resourceSpans\": [{\"scopeSpans\": [{\"spans\": [{
    \"traceId\": \"$TRACE\", \"spanId\": \"0123456789abcdef\", \"name\": \"smoke\",
    \"startTimeUnixNano\": \"1761670800000000000\", \"endTimeUnixNano\": \"1761670800500000000\"
  }]}]}]}"
NAME=$(curl -fsS "$API/traces/$TRACE" | json "[0]['name']")
[ "$NAME" = smoke ] || fail "trace not stored"
echo "ok: a trace went in and came back"

# Pages are read in full before searching. Piping curl into grep -q fails under pipefail when
# grep stops reading early, which says nothing about the page.
RUNS_PAGE=$(curl -fsS "$DASHBOARD")
[[ $RUNS_PAGE == *"smoke candidate"* ]] || fail "dashboard doesn't list the runs"
COMPARE_PAGE=$(curl -fsS "$DASHBOARD/compare?baseline=$BASELINE&candidate=$CANDIDATE")
[[ $COMPARE_PAGE == *"Real regression"* ]] || fail "dashboard compare page doesn't show the regression"
echo "ok: the dashboard shows the runs and the regression"

echo "smoke test passed"
