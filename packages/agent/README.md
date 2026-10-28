# signalfloor-agent

A small retrieval agent that answers multi-hop questions from the HotpotQA dataset. It is the
system under test for signalfloor: change something in the agent, run the eval, and use
signalfloor to see if the change really helped.

This package is not published to PyPI. See [ADR 0002](../../docs/adr/0002-reference-agent.md)
for why it exists and how it is built.

## Retrieval results

Measured on the first 200 questions of the HotpotQA dev set, with all 1,991 passages from
those questions pooled into one corpus. Recall@k is the share of the two supporting passages
that show up in the top k results, averaged over questions.

| Retriever | Recall@2 | Recall@5 | Recall@10 |
|---|---|---|---|
| BM25 | 0.552 | 0.715 | 0.902 |
| Dense, nomic-embed-text | 0.723 | 0.850 | 0.935 |
| Hybrid, reciprocal rank fusion | 0.642 | 0.848 | 0.955 |

Hybrid search is often assumed to beat either method alone. Here signalfloor says otherwise:

```console
$ signalfloor compare recall_dense_k2.jsonl recall_hybrid_k2.jsonl
change      -0.0800  (95% CI -0.1175 to -0.0425)
verdict     regression

$ signalfloor compare recall_dense_k10.jsonl recall_hybrid_k10.jsonl
change      +0.0200  (95% CI -0.0025 to +0.0425)
verdict     no detectable change
```

At k=2 hybrid is really worse, because the weaker BM25 ranking pulls good dense results down.
At k=10 its small lead is within noise. So the agent uses dense retrieval by default.

Building the dense index for 1,991 passages took about 9.5 minutes on a 2020 Intel MacBook Pro.
The embeddings are cached, so later runs start in seconds.

## Running an eval

You need [Ollama](https://ollama.com) running with the two models pulled:

```bash
ollama pull qwen3:1.7b
ollama pull nomic-embed-text
```

Then run the agent over the first 100 questions and compare two versions:

```bash
signalfloor-agent eval --questions 100 --prompt v1 --out results/v1.jsonl
signalfloor-agent eval --questions 100 --prompt v2 --out results/v2.jsonl
signalfloor compare results/v1.jsonl results/v2.jsonl
```

If a run is stopped, run the same command again and it picks up where it left off. The first
run builds the embedding index, which takes about 10 minutes on a laptop CPU.

## Experiment: does the v2 prompt help?

Running v1 on real questions showed two problems. The agent often answered "Yes" to questions
that were not yes or no questions, and it often stopped after one search. The v2 prompt tells
it to answer yes or no only for yes or no questions, and to usually search twice.

Each run is 100 questions with qwen3 1.7B through Ollama, about 14 minutes on a 2020 Intel
MacBook Pro. v1 was run three times to measure noise. The result files are in
[results/](results).

| Run | F1 | Exact match | Searches per question | Supporting recall |
|---|---|---|---|---|
| v1, run 1 | 0.155 | 0.120 | 0.86 | 0.530 |
| v1, run 2 | 0.144 | 0.110 | 0.84 | 0.515 |
| v1, run 3 | 0.142 | 0.110 | 0.83 | 0.505 |
| v2 | 0.238 | 0.180 | 0.65 | 0.425 |

What signalfloor says:

- **v2 really improves F1.** Against each of the three v1 runs the change is +0.084, +0.095 and
  +0.096, and every 95% interval is above zero.
- **The noise floor is small.** Across the three identical v1 runs the mean moved by at most
  0.016, and only 3 of 100 cases changed score. The v2 gain is about five times that.
- **Exact match alone cannot confirm it.** Its change of +0.06 has an interval from -0.02 to
  +0.14, so F1, which gives partial credit, is the more sensitive metric here.
- **v2 also made something worse.** Supporting recall dropped by 0.105, interval -0.185 to
  -0.025, a real regression.

Looking at the answers explains both results. v1 said yes or no to 49 of the 88 questions
that were not yes or no questions. v2 did that only 6 times, which is where the gain comes
from. But the instruction to search twice backfired: v2 answered 37 questions without
searching at all, against 21 for v1, so it found less of the evidence.

The lesson is the reason signalfloor exists. Reading only the headline score would have shipped
v2 as a clean win and missed that it made the agent search less. The next step is to require a
search before answering in the graph itself instead of asking for it in the prompt.
