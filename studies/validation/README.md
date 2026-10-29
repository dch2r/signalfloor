# Validation study: planted regressions in real agent results

Does signalfloor make better release calls than the rule most teams use, "fail if the mean
dropped by more than X"? I planted regressions of known size into real agent results and
scored every call as right or wrong.

The study also found a bug in signalfloor's own pass rule. It is fixed, and the table shows
the rule before and after.

## Setup

- **Cases.** The 100 HotpotQA questions the [reference agent](../../packages/agent) answered
  in three identical v1 runs (qwen3:1.7b, temperature 0). The score is F1. 74% of the
  answers score 0, so the data is sparse like a lot of real eval data.
- **Baseline and candidate.** Each trial takes two different runs, so the real run-to-run
  noise is in every comparison. In these runs it is small: two reruns disagree on 2 of
  100 questions.
- **Planted regression.** The candidate has some correct answers set to F1 0, chosen at
  random, until the mean has dropped by the planted amount. That is what a change that
  breaks a subset of questions looks like. A case is all or nothing, so the true drop runs a
  little over the target. For example, a planted 0.03 averages 0.034.
- **Eval size.** An eval of n cases is drawn from the 100 questions with replacement.
  Rows with n = 200 reuse the same 100 questions and are the weakest evidence here.
- **Trials.** 1,000 per cell, 24,000 in all. Each comparison uses signalfloor's defaults
  (95% interval, 10,000 resamples).

Rules compared, all on the same trials:

| Rule | Ships when |
|---|---|
| naive > X | the mean dropped by X or less |
| verdict | signalfloor's interval is not wholly below zero |
| interval-only pass | the old margin rule: the interval sits at or above -0.02 |
| pass | the fixed margin rule with margin 0.02 (see below) |

## Results

Shares of trials. Full table: [summary.md](summary.md).

**Reruns of the same setup (planted drop 0).** A good release should ship.

| n | naive > 0.01 fails | naive > 0.02 fails | verdict says regression | margin says fail | margin passes |
|---:|---:|---:|---:|---:|---:|
| 20 | 7.7% | 6.5% | 0.3% | 0.0% | 0.0% |
| 50 | 12.5% | 7.9% | 1.2% | 0.0% | 0.0% |
| 100 | 17.9% | 6.6% | 8.8% | 0.0% | 0.1% |
| 200 | 18.4% | 4.7% | 24.2% | 0.0% | 54.0% |

**Real regressions larger than the margin.** A bad release should not ship.

| planted drop | n | naive > 0.02 ships | interval-only pass ships | pass ships |
|---:|---:|---:|---:|---:|
| 0.03 | 20 | 52.5% | 29.9% | 0.0% |
| 0.03 | 50 | 36.9% | 15.8% | 0.0% |
| 0.03 | 100 | 27.1% | 4.5% | 0.0% |
| 0.03 | 200 | 20.3% | 1.6% | 0.1% |
| 0.05 | 20 | 30.8% | 15.0% | 0.0% |
| 0.05 | 100 | 7.5% | 1.0% | 0.0% |
| 0.08 | 20 | 18.3% | 5.9% | 0.0% |

## What it shows

1. **The naive rule ships real regressions.** With a threshold of 0.02 it shipped a 3
   point drop in half of 20 case evals and in a fifth of 200 case evals. A tighter
   threshold of 0.01 catches more, but then fails up to 18% of harmless reruns. No single
   threshold works at every eval size, because the threshold ignores how noisy the mean is.

2. **signalfloor's old pass rule had the same flaw in a smaller form.** It passed a real
   3 point regression in 30% of 20 case evals. A change that breaks 4 of 100 questions
   leaves no trace in a 20 case eval 44% of the time. Then every difference is zero, the
   bootstrap interval shrinks to [0, 0], and the rule "proved" there was no drop. A
   bootstrap only knows the cases it was given.

3. **The fix counts the cases the eval may have missed.** If a share p of all cases had
   broken, an eval of n cases would show none of them with chance (1 - p)^n. The largest p
   that still happens 2.5% of the time is 1 - 0.025^(1/n), about 3.7 / n (the rule of
   three). Those cases could each drop as far as a score can. "Largest drop not ruled out"
   now includes them, and pass needs it to be within the margin. After the fix, signalfloor
   shipped a regression larger than the margin in at most 0.1% of trials, against up to
   30% before.

4. **The price is that a margin needs enough cases.** Below a certain size, even an eval
   where nothing changed can't pass:

   | margin | cases needed |
   |---:|---:|
   | 0.01 | 368 |
   | 0.02 | 183 |
   | 0.03 | 122 |
   | 0.05 | 72 |
   | 0.10 | 36 |

   So at margin 0.02 the fixed rule almost never passed an eval under 183 cases, even when
   nothing had changed. It passed 0.1% at n = 100, where the sample happened to show a
   clear gain. That is the honest answer. The data in those evals can't tell a safe
   release from one that broke 3% of the questions. The CLI and the dashboard now print the
   number of cases the margin needs, so the fix is to add cases or accept a wider margin,
   not to guess.

5. **The verdict alone is not a release gate.** On reruns of the same setup, the verdict
   called a regression in 24% of 200 case evals. Two reruns really do differ on a couple
   of questions, and with enough cases the bootstrap correctly finds that difference. But
   it is run-to-run noise, not a regression. The margin absorbs it (0% fail), and
   `signalfloor flaky` measures it. Gate releases on `--margin`, not on the verdict.

## Limits

- One agent, one metric, 100 questions. The n = 200 rows reuse those questions.
- One kind of damage: correct answers broken outright. A change that lowers every score a
  little is easier for the bootstrap, and the unseen cases bound is more cautious than
  needed there.
- The bound assumes an unseen broken case can lose the full score range. With scores
  between 0 and 1 that is 1. Outside that range signalfloor uses the range it saw.
- Run-to-run noise in these runs is small (temperature 0). An agent with more of it makes
  the naive rule worse and makes the margin matter more.

## Rerun it

```console
uv run python studies/validation/run.py
```

It takes under 3 minutes with a fixed seed and writes `summary.md`. Every trial goes to
`results.csv`, which is not committed.
