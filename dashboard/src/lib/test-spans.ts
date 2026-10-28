import type { Span } from "./api";

/** A span for tests. Times are milliseconds after a fixed start. */
export function span(
  id: string,
  parent: string | null,
  startMs: number,
  durationMs: number,
  extra: Partial<Span> = {},
): Span {
  return {
    trace_id: "t".repeat(32),
    span_id: id,
    parent_span_id: parent,
    name: id,
    service_name: "signalfloor-agent",
    start_time: new Date(Date.UTC(2026, 9, 28, 18, 0, 0) + startMs).toISOString(),
    duration_ms: durationMs,
    status: "unset",
    status_message: null,
    attributes: {},
    ...extra,
  };
}
