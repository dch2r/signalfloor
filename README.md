# signalfloor

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

## Status

Early development. The `compare` command works today. Judge calibration, flaky case detection,
trace ingestion and the CI integration are still to come.

## Quick start

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

## Development

You need [uv](https://docs.astral.sh/uv/) installed. Then:

```bash
git clone https://github.com/dch2r/signalfloor.git
cd signalfloor
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
uv run pytest
```

## License

Apache 2.0. See [LICENSE](LICENSE).
