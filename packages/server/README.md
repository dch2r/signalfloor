# signalfloor-server

The HTTP API for signalfloor. It stores eval runs in Postgres so they can be listed and compared
later, instead of passing JSONL files around. This package is not published to PyPI.

You upload each eval run once. Any two runs can then be compared with the same paired bootstrap
as `signalfloor compare`, and the answer is the same to the last digit.

## Running it

You need Postgres 14 or newer. On a Mac, [Postgres.app](https://postgresapp.com) is the easiest
way to get it. Create a database, apply the migrations and start the server:

```bash
createdb signalfloor
uv run signalfloor-server migrate
uv run signalfloor-server serve
uv run signalfloor-server worker    # in a second terminal, for background jobs
```

The API docs are then at http://127.0.0.1:8000/docs.

The server reads its settings from environment variables:

| Variable | Default |
|---|---|
| `SIGNALFLOOR_DATABASE_URL` | `postgresql+asyncpg://localhost/signalfloor` |
| `SIGNALFLOOR_API_KEYS` | empty, so the API is open |

## Endpoints

| Method and path | What it does |
|---|---|
| `POST /runs` | Upload a run. Returns its id, case count and mean score. |
| `GET /runs` | List runs, newest first. Takes `limit`, `offset` and `label=key=value` filters. |
| `GET /runs/{id}` | One run. |
| `DELETE /runs/{id}` | Delete a run and its cases. |
| `GET /runs/{baseline}/compare/{candidate}` | Paired bootstrap of candidate minus baseline. Takes `confidence`, `n_resamples` and `seed`. |
| `GET /runs/{baseline}/diff/{candidate}` | How many cases got worse, better or stayed the same, with the biggest drops and gains. Takes `limit`. |
| `GET /runs/{id}/cases/{case_id}` | One case's score, with its trace if it has one. |
| `POST /v1/traces` | OpenTelemetry trace ingestion over OTLP/HTTP. |
| `GET /traces/{trace_id}` | Every span in a trace, in start order. |
| `POST /jobs/compare` | Queue a comparison for the worker. Allows up to 1,000,000 resamples. |
| `GET /jobs/{id}` | A job's status, result or error. |

Upload a run:

```bash
curl -X POST localhost:8000/runs -H 'content-type: application/json' -d '{
  "name": "prompt v2",
  "labels": {"prompt": "v2", "model": "qwen3:1.7b"},
  "cases": [{"id": "q1", "score": 1.0}, {"id": "q2", "score": 0.0}]
}'
```

Then compare it with an earlier run:

```bash
curl "localhost:8000/runs/<baseline id>/compare/<candidate id>?seed=0"
```

```json
{"delta": 0.0835, "ci_low": 0.0115, "ci_high": 0.1595, "verdict": "improvement", ...}
```

That is the real result for the two prompt versions of the [reference agent](../agent/README.md).

Some limits keep one request from tying up the server. A run can have up to 100,000 cases and a
comparison up to 100,000 resamples. Case ids must be unique within a run, and scores must be
finite numbers. Two runs can only be compared if they have exactly the same case ids.

## Traces

`POST /v1/traces` is a standard OTLP/HTTP endpoint, so any OpenTelemetry SDK can send to it by
setting its exporter endpoint to `http://<server>/v1/traces`. It takes protobuf or JSON,
gzipped or not, up to 10 MB once unzipped.

To link a case to its trace, upload the case with a `trace_id`:

```json
{"id": "q1", "score": 0.0, "trace_id": "1e25e12afbd6768c9b2686196163c206"}
```

`GET /runs/{id}/cases/q1` then returns the score and the spans together. Spans can arrive before
or after the run is uploaded.

Some details that matter in practice:

- Exporters retry failed requests, so the same span can arrive twice. Spans are keyed by trace
  and span id and duplicates are dropped.
- A span with a malformed id is rejected on its own and reported back as a partial success.
  The rest of the batch is kept.
- In OTLP JSON, ids are hex, but protobuf's JSON parser reads them as base64. They are
  converted before parsing, or every id from a JSON exporter would be wrong.
- Postgres can't store the NUL character, and one in any attribute made it reject the whole
  batch. NUL characters are removed, and NaN and infinity are stored as strings.

## Background jobs

Some work is too slow for a request. `POST /jobs/compare` queues it and answers 202 with a job
id. `signalfloor-server worker` runs queued jobs, and `GET /jobs/{id}` shows the status:
queued, running, succeeded or failed.

The queue is a table in Postgres, not Redis. A worker claims a job with
`SELECT ... FOR UPDATE SKIP LOCKED`, so you can run as many workers as you like:

- Two workers never run the same job. A test runs four workers on 20 jobs and checks each
  job ran once. Without the row lock, one job ran three times.
- A claimed job has a 10 minute lease. If its worker dies, another worker takes the job when
  the lease runs out.
- A worker that lost its lease can't overwrite the result of the worker that took over.
- A job that raises is retried after 2, then 4 seconds, up to 3 attempts. A job that can't
  succeed, such as comparing a run that was deleted, fails at once.
- On SIGTERM the worker finishes its current job and exits, which is what Kubernetes expects.

## Deleting old spans

Spans pile up. Delete the ones older than 30 days with:

```bash
uv run signalfloor-server prune-spans --older-than-days 30
```

It deletes 10,000 spans per transaction so a big cleanup doesn't lock the table for long. Run
it on a schedule, for example as a Kubernetes CronJob.

## API keys and who this is for

Set `SIGNALFLOOR_API_KEYS` to one or more keys, separated by commas. Every endpoint except the
health checks then needs `Authorization: Bearer <key>`:

```bash
SIGNALFLOOR_API_KEYS=key-one,key-two uv run signalfloor-server serve
curl -H "Authorization: Bearer key-one" localhost:8000/runs
```

More than one key lets you rotate without downtime: add the new key, move the clients over,
then remove the old one. Agents send the key with OpenTelemetry's standard setting,
`OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer key-one"`. The dashboard sends
`SIGNALFLOOR_API_KEY` from its server, so the key never reaches a browser.

Without keys the API is open to anything that can reach it, and the server logs a warning at
startup. That's fine on your own machine and nowhere else.

**What this is built for: one team, on a network it controls.** Be clear about what it isn't:

- **There are no users or projects.** Any key can read, change and delete everything. Two
  teams that must not see each other's data need two deployments.
- **Traces can be sensitive.** Prompts and passages are never recorded, but search queries,
  answers and any attribute an agent adds are stored as sent. Redact at the source.
- **The dashboard has no login.** Anyone who can open it sees every run. Put it behind your own
  sign in, such as an SSO proxy or a VPN.
- **There are no per client quotas.** Request sizes and comparison costs are capped, and
  concurrent bootstraps are limited, but one client with a key can still keep the server busy.

Per project access, a dashboard login and quotas would be the next steps toward a service
shared by several teams.

## Health checks

- `GET /health/live` answers 200 as long as the process is up.
- `GET /health/ready` also checks the database and answers 503 when it can't reach it.

They are split so that Kubernetes can stop sending traffic to a pod that lost its database
without restarting it.

## Schema changes

Migrations live in `src/signalfloor_server/migrations` and ship inside the package, so the
deployed server can migrate its own database. After changing `models.py`, add a new file under
`migrations/versions`. A test compares the models with the migrated database and fails if they
don't match, so a forgotten migration is caught in CI.

## Tests

The tests need a Postgres database they are allowed to wipe. By default they use
`signalfloor_test` on localhost:

```bash
createdb signalfloor_test
uv run pytest packages/server
```

Set `SIGNALFLOOR_TEST_DATABASE_URL` to use a different one. CI runs them against a Postgres
service container.
