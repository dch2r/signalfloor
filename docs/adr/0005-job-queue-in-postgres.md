# ADR 0005: A job queue in Postgres

- Status: Accepted
- Date: 2026-10-28

## Context

Some work doesn't fit in a request. Today that is a comparison with very many resamples.
Soon it will be things like having an LLM judge score a whole run, which can take minutes.
That work needs to run in the background, survive a crashed worker and report back.

## Decision

1. Keep the queue in a Postgres table instead of adding Redis with Celery or RQ. The server
   already depends on Postgres, so there is no new service to run, back up or monitor. A job
   can be queued in the same transaction as the data it needs.
2. Claim jobs with `SELECT ... FOR UPDATE SKIP LOCKED`. The row lock is what stops two workers
   from taking the same job. SKIP LOCKED makes a worker pass over jobs another worker holds
   instead of waiting for them, so workers don't queue up behind each other.
3. Make each claim a lease. One `run_after` column means "due at" for a queued job and "lease
   ends at" for a running one, so the query that finds new jobs also finds jobs whose worker
   died.
4. Use the attempt count as a fencing token. A worker records its outcome only if the count
   still matches its own claim.
5. Retry with exponential backoff up to `max_attempts`. Errors that retrying can't fix fail at
   once.
6. Poll once a second when idle. LISTEN and NOTIFY would cut that delay, but a second doesn't
   matter for this work.
7. Delete old spans with a command, `prune-spans`, not with a job the worker schedules for
   itself. Running it on a schedule is the job of cron or a Kubernetes CronJob.

## Consequences

- Honest note: a comparison of 100 cases with 1,000,000 resamples finished in under a second
  and gave the same answer as 10,000. The queue isn't needed for comparisons. It is in place
  for slow work to come.
- Postgres handles a queue of this size easily. At thousands of jobs per second a dedicated
  broker would be the better choice, and that is far beyond this project.
