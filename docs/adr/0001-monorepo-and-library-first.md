# ADR 0001: Monorepo with a uv workspace, library first

- **Status:** Accepted
- **Date:** 2026-10-27

## Context

signalfloor will eventually have several deployable parts: a Python library and CLI,
an API service, background eval workers, and a web dashboard. They share data models
(eval runs, cases, scores) and must change together while the design is young.

The project's differentiator is statistical: deciding whether a score change between two
eval runs is real or noise. That logic is useful on its own, without any server, database,
or UI — for example as a single command in a CI job.

## Decision

1. **One repository** containing every component, with Python packages managed as a
   [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/) under `packages/`.
   One lockfile, one set of lint/type/test tooling at the root.
2. **Build the core library first.** `packages/signalfloor` holds the statistics engine and
   CLI, has no infrastructure dependencies, and is publishable to PyPI on its own. Services
   added later depend on it rather than the other way around.
3. **Strict quality gates from the first commit:** `ruff` for lint and format, `mypy --strict`,
   `pytest` with coverage, pre-commit hooks, and CI on Python 3.11–3.13.

## Consequences

- A user can adopt the regression gate with `pip install signalfloor` before any hosted
  component exists, which is the shortest path to real users.
- The core stays free of web and database concerns, which keeps it fast to test.
- Cross-cutting changes land in one pull request instead of coordinated releases.
- When the TypeScript dashboard arrives it will need its own toolchain inside the same repo;
  that is accepted in exchange for atomic changes across components.
