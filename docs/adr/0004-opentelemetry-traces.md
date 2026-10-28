# ADR 0004: OpenTelemetry for agent traces

- Status: Accepted
- Date: 2026-10-28

## Context

signalfloor says whether a score changed. The next question is always why. To answer it, we
need to see what the agent did on a single case: which searches it ran, what came back, and
what the model did with it.

## Decision

1. Instrument the agent with OpenTelemetry, not a custom logging format. Teams already run
   OpenTelemetry, and any backend that speaks OTLP can read our traces.
2. Follow the OpenTelemetry GenAI conventions for span names and attributes: `invoke_agent`,
   `chat` and `execute_tool`, with `gen_ai.*` attributes for the model, tokens and tool.
   Attributes of our own use the `signalfloor.` prefix.
3. Don't record prompts or passage text. The conventions make message content opt-in because
   it often holds private data. Here it would also copy HotpotQA text into the database.
4. Make the server an OTLP/HTTP receiver at the standard `/v1/traces` path, with both protobuf
   and JSON. We don't run a separate OpenTelemetry Collector or Jaeger. One less service to run
   on a laptop, and traces sit in the same database as the scores they explain.
5. Link a case to its trace through a `trace_id` on the case. The eval runner opens one root
   span per case and writes its trace id into the results file.

## Consequences

- Opening a case shows its score and its full trace in one request.
- Without `--otlp-endpoint`, OpenTelemetry stays a no-op and costs nothing.
- The server has to handle what a real receiver handles: retries, gzip, partial success and
  bad input. Each of those has a test.
- Spans grow without limit. A retention job to delete old spans is planned for the background
  worker.
