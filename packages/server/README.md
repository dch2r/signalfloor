# signalfloor-server

The HTTP API for signalfloor. It stores eval runs in Postgres so they can be listed and compared
later, instead of passing JSONL files around. This package is not published to PyPI.

So far it has health checks and the database schema. Endpoints for uploading and comparing runs
come next.

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
