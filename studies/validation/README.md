# Validation study: planted regressions in real agent results

Does signalfloor make better release calls than "fail if the mean dropped by more than X",
the rule most eval checks use? I planted changes of known size into real agent results and
scored every call as right or wrong. A good release gate has to do four things at once, so
all of them are reported side by side:

- pass changes you would ship (approval)
- not fail them (false rejection)
- not pass changes you wouldn't ship (unsafe approval)
- say when it can't tell, and how many cases it would need (inconclusive, cost)

## Setup

- **Data.** The reference agent's v1 prompt on HotpotQA, scored by F1. Most answers score 0,
  so the data is sparse like a lot of real eval data. Two sets:
  - **dev**: the first 100 questions, three runs. This study first ran on these, and what it
    found shaped signalfloor's safeguards. Results here are development evidence.
  - **fresh**: the next 100 questions, two new runs. The study ran on them only once the
    safeguards were final, and nothing was changed after. They are the check. Their two runs
    differ on 1 question of 100.
- **Trials.** Each trial takes a baseline run and a different candidate run, so real
  run-to-run noise is in every comparison. It damages the candidate by a known amount, draws
  an eval of n cases with replacement (20, 50, 100 or 200), and asks each rule for a release
  call. 1,000 trials for every damage pattern, planted drop and eval size, 72,000 per data
  set. Each comparison uses 2,000 resamples.
- **Damage**, three patterns:
  - **break**: random correct answers drop to 0. A change that breaks a subset.
  - **partial**: every answer loses the same share of its credit. A change that hurts a
    little everywhere.
  - **churn**: 5% of wrong answers become right, and more right answers break, to reach the
    planted drop. Many cases move both ways, which is where false failures come from.
- **Margins.** 0.02 and 0.05. With scores from 0 to 1, a margin of 0.02 needs 183 cases
  before any eval can pass it, and 0.05 needs 72. So the two margins show the rules below and
  above that size.
- **Scoring.** A planted drop of at most half the margin is a change you'd ship. One above
  the margin is a change you wouldn't. Drops in between are run but not scored.

Rules compared on the same trials:

| Rule | Pass | Fail |
|---|---|---|
| naive | mean dropped by at most the margin | otherwise |
| interval-only | bootstrap interval at or above -margin | interval below -margin |
| 0.3.0 | interval-only, with the lower end widened for unseen cases | as interval-only |
| bounds (current) | lower bound at or above -margin | upper bound below -margin |

## Results

These are the **fresh** results, the held-out check. The dev results tell the same story,
with individual cells up to 6 points apart, and are in the [dev table](summary-dev.md).

**Margin 0.05** (72 cases needed to pass). Acceptable: planted drop 0 to 0.02. Bad: 0.08.

| n | rule | acceptable: pass | acceptable: fail | acceptable: more evidence | bad: pass | bad: fail |
|---:|---|---:|---:|---:|---:|---:|
| 20 | naive | 85.3% | 14.7% | | 36.4% | 63.6% |
| 20 | 0.3.0 | 0.0% | 0.2% | 99.8% | 0.0% | 4.7% |
| 20 | bounds | 0.1% | 0.0% | 99.9% | 0.0% | 0.1% |
| 100 | naive | 93.3% | 6.7% | | 18.0% | 82.0% |
| 100 | 0.3.0 | 25.1% | 0.1% | 74.8% | 0.0% | 22.4% |
| 100 | bounds | 52.6% | 0.1% | 47.3% | 0.6% | 3.7% |
| 200 | naive | 96.7% | 3.3% | | 11.7% | 88.3% |
| 200 | 0.3.0 | 47.2% | 0.0% | 52.7% | 0.0% | 37.1% |
| 200 | bounds | 70.6% | 0.0% | 29.3% | 0.1% | 14.0% |

**Margin 0.02** (183 cases needed to pass). Acceptable: 0 or 0.01. Bad: 0.03 to 0.08.

| n | rule | acceptable: pass | acceptable: fail | acceptable: more evidence | bad: pass | bad: fail |
|---:|---|---:|---:|---:|---:|---:|
| 20 | naive | 75.2% | 24.8% | | 29.6% | 70.4% |
| 20 | bounds | 0.1% | 0.0% | 100.0% | 0.0% | 0.1% |
| 100 | naive | 78.9% | 21.1% | | 14.3% | 85.7% |
| 100 | bounds | 2.7% | 0.5% | 96.7% | 0.3% | 10.8% |
| 200 | naive | 79.9% | 20.1% | | 10.3% | 89.7% |
| 200 | bounds | 31.8% | 0.5% | 67.7% | 0.3% | 35.8% |

Worst case over every damage pattern and eval size:

| | naive | interval-only | 0.3.0 | bounds |
|---|---:|---:|---:|---:|
| unsafe pass, dev | 35.0% | 16.9% | 0.1% | 1.0% |
| unsafe pass, fresh | 47.0% | 20.8% | 0.1% | 1.2% |
| false fail, dev | 40.8% | 2.5% | 2.5% | 2.1% |
| false fail, fresh | 44.0% | 2.2% | 2.2% | 1.7% |

Full tables, including every damage pattern: [dev](summary-dev.md), [fresh](summary-fresh.md).

## What it shows

1. **The naive rule is wrong in both directions.** On fresh data it shipped up to 47% of
   bad changes and failed up to 44% of acceptable ones, worst on churn, where many cases
   move both ways. More cases help but don't fix it: at 200 cases and margin 0.02 it still
   fails 20% of acceptable changes, because a fixed threshold ignores how noisy the mean is.

2. **The bounds rarely make a wrong call.** At most 1.2% unsafe passes and 1.7% false fails
   on fresh data, both under the nominal 2.5%. Fresh and dev agree, so the safeguards were
   not just fitted to the data that shaped them.

3. **The price is a lot of "needs more evidence".** Below the case count a margin needs,
   the bounds almost never approve anything. At margin 0.02 they passed 0.1% of acceptable
   changes at 20 cases, 2.7% at 100 and 32% at 200. A wider margin is what makes small evals
   usable: at 0.05 they passed 53% at 100 cases and 71% at 200, still with at most 1.2%
   unsafe passes. Choosing the margin and the eval size together is the real decision, and
   `signalfloor compare` prints the cases a margin needs.

4. **The bounds call "fail" less often than 0.3.0.** At 100 cases and margin 0.05, 0.3.0
   failed 22% of bad changes and the bounds 4%. The rest get "needs more evidence". In CI
   that also blocks the release (exit code 3), so the bad change still doesn't ship, but a
   fail is the clearer message. That is the cost of protecting fail from tiny samples: two cases that
   both got worse used to fail with 95% confidence 25% of the time when nothing had changed.

5. **The bounds approve more than 0.3.0.** 0.3.0 widened its lower end by the full unseen
   share even when the eval had already seen the worst possible difference, so it was more
   cautious than it needed to be: 25% vs 53% approval at 100 cases and margin 0.05. Its
   unsafe pass rate was lower, 0.1% against 1.2%.

6. **The old interval-only rule was unsafe on small evals.** It shipped up to 21% of bad
   changes. The worst was breaking at 20 cases (20.8%, against 5.2% for partial damage),
   where a small eval often draws none of the broken cases. That was the finding that
   started all of this.

## Limits

- One agent, one metric, 200 questions in all. Evals of 200 cases are drawn from 100
  questions, so those rows reuse questions.
- Three damage patterns. Real changes can mix them in other ways.
- The bounds are a safeguard checked by simulation, here and in the tests. There is no proof
  of their coverage. This study is the evidence, and it covers only the cases above.
- Run-to-run noise in these runs is small (temperature 0). An agent with more of it makes
  the naive rule worse and the margin matter more.

## Rerun it

```console
uv run python studies/validation/run.py --data dev
uv run python studies/validation/run.py --data fresh
```

Each takes a few minutes with a fixed seed and writes `summary-<data>.md`. Every trial goes
to `results-<data>.csv`, which is not committed.
