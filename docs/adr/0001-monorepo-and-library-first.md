# ADR 0001: One repo, and the library comes first

- Status: Accepted
- Date: 2026-10-27

## Context

signalfloor will end up with several parts: a Python library with a command line tool, an API
server, background workers that run evals, and a web dashboard. They all share the same data
(eval runs, test cases, scores), and while the design is young they will change together a lot.

The most important part is the statistics. Deciding if a score change between two runs is real
or noise is useful on its own, with no server, database or UI. A team could use it as a single
command in their CI job.

## Decision

1. Keep everything in one repository. The Python packages live under `packages/` and are managed
   as a [uv workspace](https://docs.astral.sh/uv/concepts/projects/workspaces/), with one lockfile
   and one set of lint, type check and test tools at the root.
2. Build the core library first. `packages/signalfloor` holds the statistics and the command line
   tool. It has no infrastructure dependencies and can be published to PyPI by itself. Anything
   we add later, like the API server, depends on this library and not the other way around.
3. Turn on strict checks from the first commit: ruff for lint and formatting, mypy in strict mode,
   pytest with coverage, pre-commit hooks, and CI on Python 3.11, 3.12 and 3.13.

## Consequences

- People can start using the regression check with `pip install signalfloor` before any server
  exists. That is the fastest way to get real users.
- The core library stays free of web and database code, so its tests stay fast.
- A change that touches several parts lands in one pull request.
- The TypeScript dashboard will need its own tooling inside this repo. We accept that cost to
  keep changes in one place.
