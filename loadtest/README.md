# Load test

A [k6](https://k6.io) script for the API, and what it showed. The "Load test" workflow runs it
in CI against the docker compose stack, on demand or when this folder changes.

```bash
docker compose up --detach --wait api
k6 run loadtest/api.js                    # steady, realistic mix
loadtest/stress.sh 1                      # ramp up, report latency over time
```

Every scenario sends requests at a fixed rate, whether or not earlier ones have come back. If a
virtual user waited for each response first, a slow server would quietly get less traffic and
look faster than it is.

## Steady load

Four kinds of traffic at once, for a minute: 20 dashboard visits a second (list runs, open a run,
open a diff), 5 comparisons of two 500 case runs, 50 trace uploads of five spans each, and one
run upload of 200 cases.

| Scenario | Median | p95 |
|---|---|---|
| browse | 4 ms | 39 ms |
| compare | 34 ms | 52 ms |
| ingest | 4 ms | 9 ms |
| upload | 17 ms | 27 ms |

116 requests a second, none failed. At this load the server is barely busy.

## Stress

Over three minutes, dashboard visits ramp from 20 to 400 a second and comparisons from 5 to 100,
with traces steady at 50. The report splits the run into 15 second windows, because one number
for a whole ramp hides when things went wrong.

**What it found.** Comparisons are the bottleneck. Each one is a bootstrap of 10,000 resamples,
and under load they took every core and starved cheap requests like listing runs.

**A guess that was wrong.** One server process looked like the limit, so I added a `--workers`
option and ran four. It made things worse: dashboard throughput fell from about 200 to under 40
requests a second and up to 8% of requests failed. One process was already using 3.4 of the 4
cores, because numpy releases Python's lock while it computes. Four processes, each with its own
pool of CPU heavy threads, just fought over the same cores. The option is still there, and still
defaults to one process.

Adding it also turned up an old bug. The `signalfloor-server` command pointed at a `__main__`
module that started the CLI as soon as it was imported. Every extra worker process imports it
again, so each one tried to start a whole server and failed to bind the port.

**What helped.** Two changes to comparisons:

- Results with a fixed seed are cached. Runs never change, so the same inputs always give the
  same answer, and the dashboard always uses seed 0.
- At most one fewer bootstrap than there are cores runs at a time. The rest wait their turn
  instead of starving everything else.

To keep it honest, half the comparisons in the stress test after this change have no seed, so
they can never be cached. Even with that harder mix, the median held up much longer:

| Window | Before: browse p50, compare p50 | After: browse p50, compare p50 |
|---|---|---|
| 60 to 75 s | 1805 ms, 1956 ms | 62 ms, 160 ms |
| 90 to 105 s | 2262 ms, 2369 ms | 75 ms, 233 ms |

Dashboard throughput in the 90 to 105 second window went from 165 to 200 requests a second.

**What didn't improve.** The tail. p95 still climbs to 7 to 10 seconds near the top of the ramp.

## Limits of these numbers

- **k6 runs on the same machine as the server.** A GitHub runner has 4 cores, and k6 with
  hundreds of virtual users, Postgres and the API all share them. Part of what the stress test
  measures is the load generator competing with the server. A fair measurement needs k6 on a
  separate machine.
- **p95 is high from the very start of the stress run**, about 2.7 s in the first 15 seconds, at
  a rate the steady test handles at 39 ms. I don't know why yet.
- Trace ingestion stops in the stress run once k6 runs out of virtual users for it. That is a
  limit of the test, not a measurement of the ingest endpoint.

Read the stress results as "where it bends and what helps", not as capacity numbers.
