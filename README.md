# signalfloor

[![PyPI](https://img.shields.io/pypi/v/signalfloor)](https://pypi.org/project/signalfloor/)
[![Python](https://img.shields.io/pypi/pyversions/signalfloor)](https://pypi.org/project/signalfloor/)
[![CI](https://github.com/dch2r/signalfloor/actions/workflows/ci.yml/badge.svg)](https://github.com/dch2r/signalfloor/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](LICENSE)

Find out if a drop in your LLM eval scores is a real regression or just noise.

## The problem

You change a prompt, switch to a new model, or tweak your retriever. You rerun your evals and
accuracy goes from 82% to 80%. Did you break something?

Most eval tools show you the two numbers and leave the decision to you. But with a few hundred
test cases, a 2 point drop can easily happen by chance. So teams either ship real regressions
because they look small, or waste days chasing changes that were never there.

## What signalfloor does

signalfloor compares two eval runs and tells you if the difference is real.

- It compares the two runs case by case and gives you a confidence interval for the change,
  using a paired bootstrap.
- It measures how often your LLM judge agrees with human labels, so you know how far to trust
  its scores.
- It finds flaky test cases, the ones whose scores change between two identical runs.
- It reads OpenTelemetry traces, so you can use it alongside tools like Langfuse or Phoenix.
- It runs in CI and fails a pull request only when a regression is statistically real.

## Install

```bash
pip install signalfloor
```

Or run it without installing, using [uv](https://docs.astral.sh/uv/):

```bash
uvx signalfloor --help
```

Python 3.11 or newer is needed.

## Status

Alpha. The `compare`, `calibrate` and `flaky` commands and the GitHub Action work today.
Trace ingestion is next. See the [changelog](CHANGELOG.md) for what changed in
each release.

## See it on a real agent

[packages/agent](packages/agent) has a LangGraph agent that answers multi-hop HotpotQA questions
with a local model. It is used to test signalfloor on real agent output. Two findings so far:

- Hybrid search looked like the obvious choice, but at top 2 it was a real 8 point recall
  regression against dense search alone, and its small win at top 10 was noise.
- A new prompt raised F1 by about 9 points, well above a measured noise floor of 1.6 points.
  It also quietly cut retrieval recall by 10 points, which the headline score hid.

The [agent README](packages/agent/README.md) has the numbers and how to rerun them.

## Compare two eval runs

Save each eval run as a JSON Lines file with one test case per line:

```json
{"id": "q-001", "score": 0.85}
{"id": "q-002", "score": true}
```

Scores can be numbers or true/false. Then compare the two runs:

```console
$ signalfloor compare baseline.jsonl candidate.jsonl
cases       300
baseline    0.8033
candidate   0.7000
change      -0.1033  (95% CI -0.1400 to -0.0700)

verdict     regression
```

The command exits with code 1 when the candidate is a real regression and 0 otherwise, so
you can use it to fail a CI job. Run `signalfloor compare --help` to see all options,
including `--format json` for machine readable output.

## Check if your LLM judge can be trusted

If an LLM judge scores your outputs, label a sample of the same cases yourself and check how
often the judge agrees with you. Put the judge labels and the human labels in two files:

```json
{"id": "a-001", "label": 4}
{"id": "a-002", "label": "good"}
```

Labels can be numbers, true/false or text. Then run:

```console
$ signalfloor calibrate judge.jsonl human.jsonl --weights quadratic
cases       150
labels      1, 2, 3, 4, 5
weights     quadratic
agreement   81.3%
kappa       0.944  (95% CI 0.918 to 0.964)
judge bias  +0.080  (more lenient than humans)

verdict     trusted (threshold 0.6)
```

Plain agreement can fool you. If 90% of answers are good, a judge that always says "good"
agrees with humans 90% of the time without checking anything. Cohen's kappa removes the
agreement you would get by chance, so that judge scores 0.

Use `--weights linear` or `--weights quadratic` for ordered ratings like 1 to 5, so a 4
against a human 5 counts as close. The judge is trusted only when the whole confidence
interval is above the threshold. With too few labelled cases the verdict is inconclusive
and the command tells you to label more. It exits with code 0 only when the judge is trusted.

## Find flaky cases and your noise floor

Run the same eval a few times without changing anything, then pass all the result files:

```console
$ signalfloor flaky rerun1.jsonl rerun2.jsonl rerun3.jsonl rerun4.jsonl rerun5.jsonl
runs        5
cases       300
run means   0.8367, 0.8400, 0.8367, 0.8233, 0.8267
noise floor 0.0126
noise band  +/-0.0246  (95% of reruns stay within this)
flaky       27 of 300 cases (9.0%)

case   spread  scores
q-037  1.000   0 1 1 0 0
q-040  1.000   1 1 0 0 1
...
```

The noise band is the most useful number here. On this suite, any change smaller than about
2.5 points could come from rerunning the same thing, so do not read anything into it.

A case is flaky when its score moves between runs. By default any movement counts, which
suits pass/fail scores. For continuous scores set `--tolerance`, for example 0.1. The command
exits with code 1 when more than 5% of cases are flaky. Change that with `--max-flaky-rate`.

## Use it in GitHub Actions

Add a step after the job that produces your eval results:

```yaml
- uses: dch2r/signalfloor@v0.2.0
  with:
    command: compare
    files: evals/baseline.jsonl evals/candidate.jsonl
```

The step fails only when the candidate is a real regression, and the result is written to
the job summary. `command` can be `compare`, `calibrate` or `flaky`. Pass any other command
line options through `options`, for example `options: --confidence 0.99`. The step also sets
an `exit-code` output.

Want to try everything first? The [examples](examples) folder has small result files.

## Development

To work on signalfloor itself you need [uv](https://docs.astral.sh/uv/) installed. Then:

```bash
git clone https://github.com/dch2r/signalfloor.git
cd signalfloor
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to send a change.

## License

Apache 2.0. See [LICENSE](LICENSE).
