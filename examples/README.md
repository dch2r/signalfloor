# Example result files

Small made up eval results you can use to try signalfloor or to test the GitHub Action.

| File | What it is |
|---|---|
| `baseline.jsonl` | 120 pass/fail results from the current version |
| `candidate-same.jsonl` | the same version run again, so only noise differs |
| `candidate-worse.jsonl` | a version that is really worse |
| `judge.jsonl` | 1 to 5 ratings from an LLM judge |
| `human.jsonl` | human ratings for the same 120 cases |

Try them:

```bash
signalfloor compare examples/baseline.jsonl examples/candidate-same.jsonl
signalfloor compare examples/baseline.jsonl examples/candidate-worse.jsonl
signalfloor calibrate examples/judge.jsonl examples/human.jsonl --weights quadratic
signalfloor flaky examples/baseline.jsonl examples/candidate-same.jsonl
```
