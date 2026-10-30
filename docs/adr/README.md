# Architecture decision records

Each record was written when the decision was made and is left as it was, so it shows what was
known at the time. Plans in them may have shipped since, or changed:

| Record | Decision | What happened later |
|---|---|---|
| [0001](0001-monorepo-and-library-first.md) | One repository, library first | The server, agent and dashboard were added on top of the library, as planned. |
| [0002](0002-reference-agent.md) | A LangGraph agent to test signalfloor on real output | Built in `packages/agent`, with run manifests added later. |
| [0003](0003-api-server-and-database.md) | FastAPI with Postgres | Built in `packages/server`. |
| [0004](0004-opentelemetry-traces.md) | Store OpenTelemetry traces | The retention it planned for the worker shipped as the `prune-spans` command instead, see 0005. |
| [0005](0005-job-queue-in-postgres.md) | A job queue in Postgres | Built as described. |
| [0006](0006-containers-tested-in-ci.md) | Containers built and tested in CI first | The Kubernetes step it mentions shipped as the Helm chart, installed on a kind cluster in CI. |
| [0007](0007-betting-confidence-intervals.md) | Decide from a confidence interval by betting | Current. |
