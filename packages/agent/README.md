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
change      -0.0800  (bootstrap 95% CI -0.1175 to -0.0425)
bounds      -0.1359 to -0.0277  (95% at any sample size, the calls below use these)
verdict     regression

$ signalfloor compare recall_dense_k10.jsonl recall_hybrid_k10.jsonl
change      +0.0200  (bootstrap 95% CI -0.0025 to +0.0425)
bounds      -0.0137 to +0.0551  (95% at any sample size, the calls below use these)
verdict     inconclusive
```

At k=2 hybrid is really worse, because the weaker BM25 ranking pulls good dense results down.
That holds under signalfloor's strictest bounds. At k=10 its small lead isn't shown to be
real. So the agent uses dense retrieval by default.

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

Each results file gets a manifest next to it, such as `results/v1.manifest.json`. It records
the settings that change the results: the prompt and its hash, the model and retrieval
settings, the digests of the model and the embedding model as Ollama reports them, a hash of
the corpus, and a hash of the agent's own code, which includes the scorer. It also records
each question's id with a hash of its text, gold answer and supporting facts, in order. A
resume must match all of it, so stopping a v1 run and resuming it with `--prompt v2` fails
instead of leaving a file that is half one prompt and half the other:

```console
$ signalfloor-agent eval --prompt v2 --out results/v1.jsonl
signalfloor-agent: error: results/v1.jsonl was started with a different setup. Resuming would mix two setups in one file:
  prompt: 'v1' before, 'v2' now
  prompt_sha256: 'f9f0...' before, '6eab...' now
Write this run to a new file, or undo the change.
```

Asking for more questions is allowed, as long as the questions already run are unchanged.
Digests must match exactly. If the digest was unknown when a run started, say because the
lookup failed, a later resume that does know it is refused, since nothing shows the earlier
results came from the same weights. Things it can't catch: a model server that never reports
a digest can swap weights behind the same name, and anything outside the agent's code, such
as a library upgrade, isn't hashed. The embedding cache is keyed by the embedding model's
digest too, so new weights never reuse old vectors. That means the first run after this
change rebuilds the index once. The older result files in `results/` were written before
manifests existed. The `fresh-v1-run*` files have version 1 manifests, from before questions
were fingerprinted.

## Tracing

Pass `--otlp-endpoint` to record an OpenTelemetry trace for every question:

```bash
uv run signalfloor-server serve
uv run signalfloor-agent eval --questions 5 --prompt v2 --out runs/traced.jsonl \
    --otlp-endpoint http://localhost:8000/v1/traces
```

If the server requires an API key, pass it the standard OpenTelemetry way:
`OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer <key>"`.

Each line of the results file then has a `trace_id`. Any OTLP/HTTP backend works, such as
Jaeger, but sending to signalfloor-server lets you open a case and its trace together.

Spans follow the OpenTelemetry GenAI conventions:

```
eval case                      case id, F1, supporting recall
  invoke_agent                 final answer, number of searches
    chat qwen3:1.7b            tool calls asked for, input and output tokens
    execute_tool search        query, titles found
    chat qwen3:1.7b
```

Prompts and passage text are not recorded. Only the model, token counts, search queries,
titles and the final answer are.

Here is one real trace from the v2 prompt, for a question the agent got wrong:

```
eval case                      8981 ms  score 0.0, supporting recall 0.5
  invoke_agent                 8981 ms  answer "Shirley Temple", 1 search
    chat qwen3:1.7b            3424 ms  asks for search, 286 tokens in
    execute_tool search          36 ms  "woman who portrayed Corliss Archer"
    chat qwen3:1.7b            5517 ms  answers, 743 tokens in
```

The question asks what government position the actress who played Corliss Archer held. The
agent found the actress and stopped there, answering with her name. It never searched for the
second fact. That is the same pattern behind the drop in supporting recall in the experiment
below, seen in a single case. The trace also shows where the time goes: the model takes 99% of
it and the search takes 36 ms.

### Traced runs of both prompts

`results/traced-v1-20q.jsonl` and `results/traced-v2-20q.jsonl` are both prompts on the first 20
questions with tracing on. On 20 questions signalfloor calls it inconclusive: F1 0.319 against
0.323, interval -0.131 to +0.151. Twenty cases are far too few to tell these prompts apart.

The traces still explain single cases. The biggest drop, question `5abd94525542992ac4f382d2`,
went from 1.0 with v1 to 0.222 with v2:

- v1 searched once and answered "YG Entertainment".
- v2 didn't search at all. It answered from memory with a full sentence: "The 2014 S/S is the
  debut album of a South Korean boy group that was formed by YG Entertainment".

v2 had the right answer. F1 punished the extra words. So part of this drop is the metric, not
the agent getting the fact wrong, and only the trace shows that. Open it in the dashboard from
the compare page.

The v1 timings in these traces are inflated. A dashboard build was running on the same laptop
during the v1 run, and one model call took 121 s. v2 ran on an idle machine at about 7 s per
question.

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

- **v2 likely improves F1, but 100 questions can't prove it.** Against each of the three v1
  runs the change is +0.084, +0.095 and +0.096, and every bootstrap interval is above zero.
  signalfloor's bounds, which hold at any sample size, reach just below zero (lower ends
  -0.021, -0.007 and -0.006), so its verdict is inconclusive. More questions would settle it.
- **The gain is bigger than rerun noise.** Across the three identical v1 runs the mean moved by
  at most 0.013, and only 3 of 100 cases changed score. With only three runs signalfloor puts
  the noise band at +/-0.043, which allows for runs moving together. The v2 gain is about twice
  that. An earlier version assumed cases vary independently and gave +/-0.016, which made the
  gain look five times the noise.
- **Exact match alone shows even less.** Its change of +0.06 has a bootstrap interval from
  -0.02 to +0.14, so F1, which gives partial credit, is the more sensitive metric here.
- **v2 likely made something worse.** Supporting recall dropped by 0.105. The bootstrap
  interval, -0.185 to -0.025, is below zero. The bounds, -0.230 to +0.013, just reach above
  it, so this too is likely but not proven on 100 questions.

Looking at the answers explains both results. v1 said yes or no to 49 of the 88 questions
that were not yes or no questions. v2 did that only 6 times, which is where the gain comes
from. But the instruction to search twice backfired: v2 answered 37 questions without
searching at all, against 21 for v1, so it found less of the evidence.

The lesson is the reason signalfloor exists. Reading only the headline score would have shipped
v2 as a clean win and missed that it made the agent search less. The next step is to require a
search before answering in the graph itself instead of asking for it in the prompt.
