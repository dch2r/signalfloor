# signalfloor

Find out if a drop in your LLM eval scores is a real regression or just noise.

```bash
pip install signalfloor
```

Three commands, each reading eval results as JSON Lines with one test case per line, like
`{"id": "q-001", "score": 1}`:

```bash
signalfloor compare   baseline.jsonl candidate.jsonl   # is this change real or noise?
signalfloor calibrate judge.jsonl human.jsonl          # can you trust your LLM judge?
signalfloor flaky     run1.jsonl run2.jsonl run3.jsonl # which cases are flaky, and what is the noise floor?
```

`compare` decides from a confidence interval by betting, which is valid at any sample size. To
gate a release, give the largest drop in mean score you accept:

```bash
signalfloor compare baseline.jsonl candidate.jsonl --margin 0.05
```

| Exit code | compare with `--margin` | compare without it | calibrate and flaky |
|---|---|---|---|
| 0 | pass: any drop is within the margin | no regression shown | the check passed |
| 1 | fail: the drop is larger than the margin | a regression | the check failed |
| 2 | bad input | bad input | bad input |
| 3 | needs more evidence: too few cases to tell | | |

Scores must lie between 0 and 1 unless you set `--score-range`. When the eval is too small to
decide, `compare` says how many cases the margin needs.

Full docs, a quickstart with example files, and a guide for your own evals are on
[GitHub](https://github.com/dch2r/signalfloor).
