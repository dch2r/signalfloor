# signalfloor

**Know whether your LLM regression is real or just noise.**

signalfloor is an open-source regression-testing platform for LLM applications and agents.
It runs eval suites against golden datasets, scores outputs with LLM judges that are
calibrated against human labels, and gates pull requests only when a quality drop is
statistically real — not when it is run-to-run noise.

> **Status:** early development. Nothing here is usable yet. Watch the repo to follow along.

## Why

Teams change a prompt, a model, or a retriever and see accuracy move by two points.
Most eval tools report that number and stop. signalfloor answers the next question:
*is that change above the noise floor?*

- **Significance, not point estimates** — paired bootstrap confidence intervals on every comparison.
- **Calibrated judges** — LLM-as-judge agreement with human labels is measured and reported, not assumed.
- **Flaky-eval detection** — test cases whose scores swing between identical runs are flagged.
- **Interop** — ingests OpenTelemetry traces, so it complements the tracing tools you already use.

## License

[Apache-2.0](LICENSE)
