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

The pre-commit hooks run lint and formatting for you on every commit.

## What we expect in a pull request

- Tests for the change. Coverage is at 100% and we want to keep it there.
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
packages/signalfloor/src/signalfloor/
    compare.py       paired bootstrap comparison of two runs
    calibration.py   judge agreement with Cohen's kappa
    stability.py     flaky cases and the noise floor
    results.py       loading JSON Lines result files
    cli.py           the signalfloor command
docs/adr/            records of design decisions and why we made them
```

## Reporting a security problem

Please do not open a public issue. See [SECURITY.md](SECURITY.md).
