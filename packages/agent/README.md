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
