# Using signalfloor on your own evals

signalfloor compares scores you already have. It doesn't run your model, and you don't need
the reference agent in this repository to use it. Any eval that gives each test case a score
can be checked.

## 1. Export one file per run

Write each eval run as JSON Lines, one test case per line, with an id and a score:

```json
{"id": "refund-policy-03", "score": 1}
{"id": "refund-policy-04", "score": 0.4}
```

Most eval tools can export this with a few lines of code. From a pandas DataFrame:

```python
df[["case_id", "score"]].rename(columns={"case_id": "id"}).to_json(
    "candidate.jsonl", orient="records", lines=True
)
```

If your fields have other names, keep them and pass `--id-key` and `--score-key` instead.
Other fields on each line are ignored, so you can export whole result rows.

## 2. Keep case ids stable

Cases are paired by id, so the same test case needs the same id in every run. Use an id from
your dataset, not a row number that shifts when cases are added or removed.

Both runs must contain the same cases. `signalfloor compare` refuses runs that differ and
lists the ids that don't match. If you add cases to your suite, rerun the baseline on the new
suite too. The server can compare runs that differ, with `shared_only=true`, but then each
missing case counts as if it could have scored anything, which widens the bounds.

## 3. Check the score range and direction

Higher scores must mean better. If your metric is lower is better, like latency or error rate,
flip it first, for example `1 - error_rate`.

Scores must lie in a known range. The default is 0 to 1, which covers accuracy, pass or fail,
F1 and most normalized judge scores. For anything else, give the range your metric can take,
not the range you happened to see:

```bash
signalfloor compare baseline.jsonl candidate.jsonl --score-range 1 5
```

## 4. Choose a margin

The margin is the largest drop in the mean score you would still ship. It is a product
decision, so start from what a drop means to your users. A margin of 0.02 on accuracy means
you accept losing 2 of every 100 answers.

Choose it before you look at a result, and keep it fixed. Widening the margin after an eval
comes back undecided only makes the check easier to pass, and says nothing new about the
change.

A small margin needs many cases. When nothing changed, an eval needs about 98 cases to pass a
margin of 0.05 and 249 to pass 0.02. The command prints the count for your margin when it
can't decide. If your suite is smaller, plan to grow it. Change the margin only if your
product requirements change on their own.

## 5. Read the result

| Result | What it means | What to do |
|---|---|---|
| pass (exit 0) | The data rules out a drop larger than the margin. | This metric's release check passes. Other checks may still apply. |
| fail (exit 1) | The data shows a drop larger than the margin. | Find what broke. The dashboard lists the cases that dropped most, or diff the two files by id. |
| needs more evidence (exit 3) | The eval is too small to tell. | Collect more cases, or treat it as a fail. Don't rerun until it passes, and don't widen the margin to get a pass: both choose the answer. |

Without `--margin` the command gives a verdict instead, regression, improvement or
inconclusive, and exits 1 only for a regression.

## 6. Know what the guarantee assumes

The bounds hold at any sample size if the cases in your eval are drawn independently from the
cases you care about. Real suites bend this in two common ways:

- **Near-duplicate cases.** Ten paraphrases of one question count as ten cases but carry
  about one case of evidence. The bounds come out narrower than they should. Group or remove
  duplicates before comparing.
- **Hand-picked suites.** A suite chosen to be hard tells you about those cases, not about
  your traffic. The result is still correct for the suite.

Rerunning the same setup also moves scores. Use `signalfloor flaky` on a few reruns to see how
much. The noise band tells you how much evidence you need, not where to set the margin: if
reruns move more than your margin, average over several reruns or add cases.

## 7. Run it in CI

Fail a pull request on the result with the GitHub Action:

```yaml
- uses: dch2r/signalfloor@v0.5.2
  with:
    command: compare
    files: evals/baseline.jsonl evals/candidate.jsonl
    options: --margin 0.05
```

Exit codes 1 and 3 both fail the step, and the full output goes to the job summary.
