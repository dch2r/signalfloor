# Contributing to signalfloor

Thanks for your interest. Bug reports, ideas and pull requests are all welcome.

## Before you start

For anything bigger than a small fix, open an issue first and describe what you want to
change. That way we can agree on the approach before you spend time on code.

## Set up

You need [uv](https://docs.astral.sh/uv/) installed.

```bash
git clone https://github.com/dch2r/signalfloor.git
cd signalfloor
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
```

The server tests also need Postgres running locally with an empty database called
`signalfloor_test`. On a Mac, install [Postgres.app](https://postgresapp.com) and run
`createdb signalfloor_test`.

## Checks

These are the same checks CI runs on every pull request:

```bash
uv run pytest --cov            # tests and coverage
uv run ruff check .            # lint
uv run ruff format --check .   # formatting
uv run mypy                    # type checking in strict mode
```

For the dashboard, from `dashboard/` with Node 24 (see `.nvmrc`):

```bash
npm ci && npm run lint && npm run typecheck && npm test
```

The pre-commit hooks run lint and formatting for you on every commit.

## What we expect in a pull request

- Tests for the change. CI fails below 100% branch coverage of the library, the agent and the
  server together (`fail_under` in `pyproject.toml`). The server tests need Postgres, so a
  local run without it reports less.
- Type hints on everything. mypy runs in strict mode.
- If you change statistics, add a test that checks the result against something known: a
  textbook example, a reference library, or a simulation.
- Update the README if you change how a command behaves.
- Keep each pull request to one change.

## Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/). Start the message with a
type, then say what you did in plain words:

```
feat: add markdown output to the compare command
fix: handle empty lines at the end of result files
docs: explain the noise band in the readme
```

Common types are `feat`, `fix`, `docs`, `test`, `refactor`, `build`, `ci` and `chore`. The
commit-msg hook checks the format for you.

## Project layout

```
packages/signalfloor/src/signalfloor/   the library and CLI, published to PyPI
    compare.py       compare two runs: verdict, decision and the cases a margin needs
    _betting.py      the confidence interval by betting that every call comes from
    calibration.py   judge agreement with Cohen's kappa
    stability.py     flaky cases and the noise floor
    results.py       loading JSON Lines result files
    cli.py           the signalfloor command
packages/agent/      a LangGraph agent on HotpotQA, used to test signalfloor on real output
packages/server/     FastAPI and Postgres: runs, traces, comparisons and the job worker
dashboard/           Next.js web view of the stored runs
deploy/helm/         the Helm chart
studies/validation/  planted regressions in real results, scored for each release rule
scripts/             the smoke test and the demo data loader
docs/                the method, a guide for your own evals, and design records (docs/adr)
```

## Reporting a security problem

Please do not open a public issue. See [SECURITY.md](SECURITY.md).
