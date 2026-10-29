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

Alpha. The `compare`, `calibrate` and `flaky` commands and the GitHub Action work today. See
the [changelog](CHANGELOG.md) for what changed in each release.

The repository has four parts:

| Part | What it is |
|---|---|
| [packages/signalfloor](packages/signalfloor) | The library and CLI, published to PyPI |
| [packages/agent](packages/agent) | A LangGraph agent used to test signalfloor on real output |
| [packages/server](packages/server) | An API that stores runs and traces and compares runs |
| [dashboard](dashboard) | A Next.js web view of the stored runs |

## See it on a real agent

[packages/agent](packages/agent) has a LangGraph agent that answers multi-hop HotpotQA questions
with a local model. It is used to test signalfloor on real agent output. Two findings so far:

- Hybrid search looked like the obvious choice, but at top 2 it was a real 8 point recall
  regression against dense search alone, and its small win at top 10 was noise.
- A new prompt raised F1 by about 9 points, about twice the noise band measured from three
  identical reruns.
  It also quietly cut retrieval recall by 10 points, which the headline score hid.

The [agent README](packages/agent/README.md) has the numbers and how to rerun them.

## Compare two eval runs

Save each eval run as a JSON Lines file with one test case per line:

```json
{"id": "q-001", "score": 0.85}
{"id": "q-002", "score": true}
```

Scores can be numbers between 0 and 1 or true/false. For another scale, such as a judge that
scores 1 to 5, add `--score-range 1 5`. signalfloor needs to know how far a score can move,
and it never guesses that from the scores it sees. Then compare the two runs:

```console
$ signalfloor compare examples/baseline.jsonl examples/candidate-worse.jsonl
cases       120
baseline    0.7500
candidate   0.5833
change      -0.1667  (95% CI -0.2750 to -0.0583)
bounds      -0.2750 to -0.0583  (the interval widened for cases the eval may have missed)

verdict     regression
```

The interval comes from a paired bootstrap. The bounds widen it for cases the eval may have
missed, and the verdict comes from the bounds. A bootstrap only knows the differences it was
given. If a change broke 4 of 100 questions, a 20 question eval misses all of them 44% of
the time, every difference is zero, and the interval is [0, 0]. If an eval of 2 cases saw two
losses, the interval is [-1, -1]. So when an eval of n cases has not seen the lowest or the
highest possible difference, the bounds allow for a share of about 3.7 / n of all cases
being out there (the rule of three). When it has seen both, as above, the bounds are the
interval.

The verdict is `regression`, `improvement` or `inconclusive`. Inconclusive means the bounds
contain zero. It does not mean nothing changed: a small eval can be inconclusive about a large
drop, so the command says how large a drop it can't rule out:

```console
$ signalfloor compare v1.jsonl v2.jsonl
cases       20
change      +0.0039  (95% CI -0.1306 to +0.1513)
bounds      -0.1681 to +0.1513  (the interval widened for cases the eval may have missed)

verdict     inconclusive
            the data can't rule out a drop of up to 0.1681
```

That is a 20 question eval, and a drop of 17 points could hide in it.

### Gate a release on a margin

To decide whether to ship, say how large a drop you accept with `--margin`. The decision is
kept apart from the verdict:

| Decision | When | Exit code |
|---|---|---|
| pass | the lower bound is at or above `-margin`, so any drop is within it | 0 |
| fail | the upper bound is below `-margin`, so the drop is larger | 1 |
| needs more evidence | anything else: the data can't tell | 3 |

```console
$ signalfloor compare v1.jsonl v2.jsonl --margin 0.02
...
decision    needs more evidence (margin 0.02)
            20 cases can't rule out a drop of 0.1684 even if nothing changed:
            a change that broke 16.8% of cases could miss every one of them
            a margin of 0.02 needs at least 183 cases
```

A margin needs enough cases, because a small eval can miss a change that breaks a few
questions outright. With scores between 0 and 1:

| Margin | 0.01 | 0.02 | 0.03 | 0.05 | 0.10 |
|---|---:|---:|---:|---:|---:|
| Cases needed to pass | 368 | 183 | 122 | 72 | 36 |

Needs more evidence fails a CI job too, because the eval was too small to show the change is
safe. Add cases or accept a wider margin. Without `--margin` the command exits with code 1
only for a proven regression.

### Does it work?

A [validation study](studies/validation) planted changes of known size into the agent's real
results, with three kinds of damage, and checked the result on 100 held-out questions. The
usual rule, "fail if the mean dropped by more than the margin", shipped up to 47% of bad
changes and failed up to 44% of acceptable ones. signalfloor's bounds shipped at most 1.2%
and failed at most 1.7%.

The price is honesty about small evals. Below the cases a margin needs, signalfloor mostly
says "needs more evidence": at margin 0.02 it approved 3% of acceptable changes at 100
cases. At margin 0.05 it approved 53% at 100 cases and 71% at 200. Pick the margin and the
eval size together.

Run `signalfloor compare --help` to see all options, including `--format json` for machine
readable output.

## Check if your LLM judge can be trusted

If an LLM judge scores your outputs, label a sample of the same cases yourself and check how
often the judge agrees with you. Put the judge labels and the human labels in two files:

```json
{"id": "a-001", "label": 4}
{"id": "a-002", "label": "good"}
```

Labels can be numbers, true/false or text. Then run:

```console
$ signalfloor calibrate examples/judge.jsonl examples/human.jsonl --weights quadratic
cases       120
labels      1, 2, 3, 4, 5
weights     quadratic
agreement   86.7%
kappa       0.955  (95% CI 0.929 to 0.975)
judge bias  +0.133  (more lenient than humans)

judge \ human       1      2      3      4      5
  1                 9      0      0      0      0
  2                 2     12      0      0      0
  3                 0      2     15      0      0
  4                 0      0      4     41      0
  5                 0      0      0      8     27

verdict     trusted (threshold 0.6)
```

Plain agreement can fool you. If 90% of answers are good, a judge that always says "good"
agrees with humans 90% of the time without checking anything. Cohen's kappa removes the
agreement you would get by chance, so that judge scores 0.

The table shows where the judge goes wrong, not just how often. Rows are the judge's labels and
columns the humans'. Here every mistake is one step too generous, which is what the positive
bias means.

Use `--weights linear` or `--weights quadratic` for ordered ratings like 1 to 5, so a 4
against a human 5 counts as close. The judge is trusted only when the whole confidence
interval is above the threshold. It exits with code 0 only when the judge is trusted.

**It won't trust a judge on thin evidence.** Every label the humans used needs at least 5
examples, or the verdict is inconclusive and says which labels are short. Without that rule,
two cases in perfect agreement came back trusted, and in simulations a judge whose true kappa
was 0.54, below the threshold, was trusted up to 20% of the time when only 10% of cases were
positive. With it, that stayed under 2% in every setting tried. Change the minimum with
`--min-per-label`.

## Find flaky cases and your noise floor

Run the same eval a few times without changing anything, then pass all the result files. This
is the reference agent run three times with nothing changed:

```console
$ signalfloor flaky v1-run1.jsonl v1-run2.jsonl v1-run3.jsonl
runs        3
cases       100
run means   0.1550, 0.1437, 0.1422
noise floor 0.0099
noise band  +/-0.0425  (95% of reruns stay within this)
            from cases +/-0.0163, from runs +/-0.0425
flaky       3 of 100 cases (3.0%)
note        with 3 runs the estimate from runs is rough. 5 or more make it reliable.

case                      spread  scores
5ae37c765542992f92d822d4  1.000   1 0 0
...
```

The noise band is the most useful number here: a change smaller than it could come from
rerunning the same thing. It is estimated two ways and the larger wins:

- **From the cases.** How much each case moves, assuming cases move independently. Precise, but
  blind to anything that shifts many cases at once, like a model update or a judge change.
- **From the runs.** How much the run means themselves move. This catches shared shifts, but
  three runs give only a rough estimate, so its band is wide. More reruns narrow it.

In a simulation where every run shares a random shift, the cases only band held 71% of fresh
reruns instead of 95%. The combined band held 97%. When cases really are independent the
combined band is about 1.3 times wider than it needs to be, which is the price of the
protection.

A case is flaky when its score moves between runs. By default any movement counts, which
suits pass/fail scores. For continuous scores set `--tolerance`, for example 0.1. The command
exits with code 1 when more than 5% of cases are flaky. Change that with `--max-flaky-rate`.

## Use it in GitHub Actions

Add a step after the job that produces your eval results:

```yaml
- uses: dch2r/signalfloor@v0.3.0
  with:
    command: compare
    files: evals/baseline.jsonl evals/candidate.jsonl
```

The step fails when the candidate is a real regression, and the result is written to the job
summary. With `options: --margin 0.05` it also fails when the eval can't show the drop is
within the margin. `command` can be `compare`, `calibrate` or `flaky`. Pass any other command
line options through `options`, for example `options: --confidence 0.99`. The step also sets
an `exit-code` output.

Want to try everything first? The [examples](examples) folder has small result files.

## Run the whole stack

With Docker installed, one command starts Postgres, the API, the background worker and the
dashboard:

```bash
docker compose up --build
```

Then open http://localhost:3000 for the dashboard and http://localhost:8000/docs for the API.
`scripts/smoke-test.sh` checks that everything works together. CI runs it on every pull request.

Set `SIGNALFLOOR_API_KEY` before `docker compose up` to require an API key. The stack is built
for one team on a network it controls. The [server README](packages/server/README.md#api-keys-and-who-this-is-for)
says what that does and doesn't cover.

To run it on Kubernetes, use the Helm chart in [deploy/helm/signalfloor](deploy/helm/signalfloor).
CI installs it on a kind cluster on every pull request.

[loadtest](loadtest) has a k6 load test and what it found about where the API bends under load.

## Development

To work on signalfloor itself you need [uv](https://docs.astral.sh/uv/) installed. Then:

```bash
git clone https://github.com/dch2r/signalfloor.git
cd signalfloor
uv sync
uv run pre-commit install --hook-type pre-commit --hook-type commit-msg
createdb signalfloor_test
uv run pytest
```

The server tests need a local Postgres. See [packages/server](packages/server/README.md).
See [CONTRIBUTING.md](CONTRIBUTING.md) for how to send a change.

## License

Apache 2.0. See [LICENSE](LICENSE).
