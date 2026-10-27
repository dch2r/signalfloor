# signalfloor

Find out if a drop in your LLM eval scores is a real regression or just noise.

```bash
pip install signalfloor
```

Three commands, each reading eval results as JSON Lines with one test case per line:

```bash
signalfloor compare   baseline.jsonl candidate.jsonl   # is this change real or noise?
signalfloor calibrate judge.jsonl human.jsonl          # can you trust your LLM judge?
signalfloor flaky     run1.jsonl run2.jsonl run3.jsonl # which cases are flaky, and what is the noise floor?
```

Each command exits with code 1 when its check fails, so you can use it to fail a CI job.

Full docs and examples are on [GitHub](https://github.com/dch2r/signalfloor).
