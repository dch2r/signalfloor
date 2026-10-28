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
```

The API docs are then at http://127.0.0.1:8000/docs.

The server reads its settings from environment variables:

| Variable | Default |
|---|---|
| `SIGNALFLOOR_DATABASE_URL` | `postgresql+asyncpg://localhost/signalfloor` |

## Endpoints

| Method and path | What it does |
|---|---|
| `POST /runs` | Upload a run. Returns its id, case count and mean score. |
| `GET /runs` | List runs, newest first. Takes `limit`, `offset` and `label=key=value` filters. |
| `GET /runs/{id}` | One run. |
| `DELETE /runs/{id}` | Delete a run and its cases. |
| `GET /runs/{baseline}/compare/{candidate}` | Paired bootstrap of candidate minus baseline. Takes `confidence`, `n_resamples` and `seed`. |

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
