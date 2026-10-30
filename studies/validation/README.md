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
  an eval of n cases with replacement (10, 20, 50, 100 or 200), and asks each rule for a
  release call. 1,000 trials for every damage pattern, planted drop and eval size, 90,000 per
  data set. Each comparison uses 2,000 bootstrap resamples.
- **Damage**, three patterns:
  - **break**: random correct answers drop to 0. A change that breaks a subset.
  - **partial**: every answer loses the same share of its credit. A change that hurts a
    little everywhere.
  - **churn**: 5% of wrong answers become right, and more right answers break, to reach the
    planted drop. Many cases move both ways, which is where false failures come from.
- **Margins.** 0.02 and 0.05. With scores from 0 to 1 and the current rule, an eval where
  nothing changed needs 249 cases to pass 0.02 and 98 to pass 0.05. An eval with a clear
  improvement can pass with fewer. So the two margins show the rules below and above that
  size.
- **Scoring.** A planted drop of at most half the margin is a change you'd ship. One above
  the margin is a change you wouldn't. Drops in between are run but not scored.

Rules compared on the same trials:

| Rule | Pass | Fail |
|---|---|---|
| naive | mean dropped by at most the margin | otherwise |
| interval-only | bootstrap interval at or above -margin | interval below -margin |
| 0.3.0 | interval-only, with the lower end widened by the rule of three | as interval-only |
| 0.4.0 | interval widened on both sides by the rule of three, past the extremes seen | upper end below -margin |
| betting (current) | lower end of the betting interval at or above -margin | upper end below -margin |

0.4.0 was tagged but never published. A review showed it fell back to the bootstrap once an
eval held both a loss and a gain, and so failed an unchanged eval of seven cases 6.25% of the
time.

## Results

These are the **fresh** results, the held-out check. The dev results tell the same story,
with no cell more than 8 points apart, and are in the [dev table](summary-dev.md).

Worst case over every damage pattern and eval size:

| | naive | interval-only | 0.3.0 | 0.4.0 | betting |
|---|---:|---:|---:|---:|---:|
| unsafe pass, margin 0.02 | 42.4% | 39.8% | 0.1% | 0.7% | 0.1% |
| unsafe pass, margin 0.05 | 48.0% | 26.2% | 0.1% | 1.3% | 0.3% |
| false fail, margin 0.02 | 42.4% | 3.3% | 3.3% | 1.8% | 0.3% |
| false fail, margin 0.05 | 31.9% | 0.5% | 0.5% | 0.1% | 0.0% |

How often each rule approves an acceptable change (planted drop at most half the margin):

| n | naive, 0.05 | 0.4.0, 0.05 | betting, 0.02 | betting, 0.05 |
|---:|---:|---:|---:|---:|
| 10 | 82.6% | 0.0% | 0.0% | 0.0% |
| 20 | 85.9% | 0.2% | 0.0% | 0.0% |
| 50 | 89.2% | 4.3% | 0.0% | 0.6% |
| 100 | 93.3% | 52.8% | 0.6% | 24.2% |
| 200 | 96.3% | 69.7% | 11.6% | 47.1% |

How often each rule fails a bad change (planted drop above the margin). The rest are
"needs more evidence", which also blocks a release in CI:

| n | naive, 0.05 | 0.3.0, 0.05 | betting, 0.02 | betting, 0.05 |
|---:|---:|---:|---:|---:|
| 50 | 74.7% | 11.2% | 1.2% | 0.6% |
| 100 | 81.8% | 20.4% | 10.8% | 4.1% |
| 200 | 86.8% | 38.6% | 33.0% | 18.7% |

Full tables, with every rule, pattern and size: [dev](summary-dev.md), [fresh](summary-fresh.md).

## What it shows

1. **The naive rule is wrong in both directions.** On fresh data it shipped up to 48% of
   bad changes and failed up to 42% of acceptable ones, worst on churn, where many cases move
   both ways. More cases help but don't fix it: at 200 cases and margin 0.02 it still fails
   20% of acceptable changes, because a fixed threshold ignores how noisy the mean is.

2. **The betting bounds almost never make a wrong call.** At most 0.3% unsafe passes and
   0.3% false fails, on dev and fresh data alike. That matches what the method promises: its
   interval holds at any sample size, which the tests also check by exact enumeration of
   every eval of up to 12 cases.

3. **The price is approval.** The bounds are about half again as wide as the bootstrap
   interval, so they approve less. At margin 0.05 they approved 24% of acceptable changes at
   100 cases and 47% at 200. 0.4.0's heuristic approved 53% and 70%, but it also failed an
   unchanged 7 case eval 6.25% of the time. At 50 cases or fewer it approved at most 0.6% at
   either margin, because an eval that small can't show a change is safe. The margin should
   come from what a drop costs, so the fix is a larger eval, not a wider margin.
   `signalfloor compare` prints the cases an unchanged eval needs for your margin.

4. **Bad changes mostly get "needs more evidence", not "fail".** At 100 cases and margin
   0.05 the bounds failed 4% of bad changes and blocked the rest as needs more evidence.
   Both block a release in CI (exit codes 1 and 3), so none shipped, but a fail is the
   clearer message, and it takes more cases.

5. **Each earlier rule had a real flaw.** Interval-only shipped up to 40% of bad changes on
   small evals that drew none of the broken cases. 0.3.0 fixed that but failed up to 3.3% of
   acceptable changes, above the 2.5% a 95% interval allows. 0.4.0 fixed fails on two cases
   but not on seven.

## Limits

- One agent, one metric, 200 questions in all. Evals of 200 cases are drawn from 100
  questions, so those rows reuse questions.
- Three damage patterns. Real changes can mix them in other ways.
- The betting interval's guarantee assumes the eval's cases are drawn independently from the
  cases you care about, and that scores stay in their range. A suite hand-picked to be hard,
  or cases that are near-copies of each other, are outside that promise.
- Run-to-run noise in these runs is small (temperature 0). An agent with more of it makes
  the naive rule worse and the margin matter more.

## Rerun it

```console
uv run python studies/validation/run.py --data dev
uv run python studies/validation/run.py --data fresh
```

Each takes a few minutes with a fixed seed and writes `summary-<data>.md`. Every trial goes
to `results-<data>.csv`, which is not committed.
