# ADR 0003: An API server backed by Postgres

- Status: Accepted
- Date: 2026-10-28

## Context

The CLI compares two JSONL files. That works for one person, but a team wants every eval run
kept in one place, so any two runs can be compared later and the history can be shown in a
dashboard. That needs a server and a database.

## Decision

1. Add `packages/server`, a FastAPI app. It is part of the workspace and never published. It
   will call the signalfloor library for the statistics, so the math lives in one place.
2. Use Postgres. Scores are stored one row per case, which lets the database pair two runs by
   case id. Postgres also has JSONB for free form run labels and pgvector if we need
   embeddings later.
3. Use SQLAlchemy 2 with asyncpg so request handlers don't block while they wait on the
   database.
4. Manage the schema with Alembic. The migrations ship inside the package so a deployed server
   can migrate its own database with `signalfloor-server migrate`. A test fails if the models
   and the migrations drift apart.
5. Split health checks into live and ready. Ready also checks the database, so an orchestrator
   can stop routing traffic to a server that lost its database without restarting it.
6. Run tests against real Postgres, locally and in CI, not SQLite. SQLite would let tests pass
   on things Postgres rejects, such as JSONB and server side UUID defaults.
7. For local development on the Mac use Postgres.app instead of Docker. It runs Postgres
   natively in about 100 MB of memory, while Docker Desktop keeps a Linux VM running. CI uses
   a Postgres service container.

## Consequences

- Contributors need Postgres running to run the server tests. The README says how.
- The test suite drops and recreates every table, so it uses its own database,
  `signalfloor_test`, and never the development one.
