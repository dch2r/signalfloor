import type { Span } from "./api";

export type TraceRow = {
  span: Span;
  depth: number;
  /** Where the span starts on the timeline, as a percentage of the whole trace. */
  offset: number;
  /** How long it runs, as a percentage of the whole trace. */
  width: number;
};

/**
 * Lay spans out as an indented tree on a shared timeline, children under their parent and
 * siblings in the order they started.
 *
 * A span whose parent never arrived is shown at the top level instead of being dropped. Spans
 * come over the network in batches, so a trace can be incomplete.
 */
export function layoutTrace(spans: Span[]): TraceRow[] {
  if (spans.length === 0) return [];

  const known = new Set(spans.map((s) => s.span_id));
  const children = new Map<string | null, Span[]>();
  for (const span of spans) {
    const parent =
      span.parent_span_id && known.has(span.parent_span_id) ? span.parent_span_id : null;
    children.set(parent, [...(children.get(parent) ?? []), span]);
  }
  for (const list of children.values()) {
    list.sort((a, b) => startMs(a) - startMs(b) || a.span_id.localeCompare(b.span_id));
  }

  const start = Math.min(...spans.map(startMs));
  const end = Math.max(...spans.map((s) => startMs(s) + s.duration_ms));
  const total = Math.max(end - start, 1);

  const rows: TraceRow[] = [];
  const seen = new Set<string>();
  const visit = (parent: string | null, depth: number) => {
    for (const span of children.get(parent) ?? []) {
      // A span listed as its own ancestor would loop forever. Bad data, but don't hang on it.
      if (seen.has(span.span_id)) continue;
      seen.add(span.span_id);
      rows.push({
        span,
        depth,
        offset: ((startMs(span) - start) / total) * 100,
        width: Math.max((span.duration_ms / total) * 100, 0.5),
      });
      visit(span.span_id, depth + 1);
    }
  };
  visit(null, 0);
  return rows;
}

function startMs(span: Span): number {
  return Date.parse(span.start_time);
}

// Attributes every span of a kind has, which say nothing about this particular span.
const HIDDEN = new Set([
  "gen_ai.operation.name",
  "gen_ai.agent.name",
  "gen_ai.tool.call.id",
  "gen_ai.tool.name",
  "gen_ai.request.model",
  // Shown only when true, below.
  "signalfloor.recovered_from_text",
]);

/** The attributes worth reading, with their namespace dropped: query, titles, tokens and so on. */
export function readableAttributes(span: Span): [string, string][] {
  const pairs: [string, string][] = [];
  for (const [key, value] of Object.entries(span.attributes)) {
    if (HIDDEN.has(key) || value === null) continue;
    pairs.push([key.replace(/^(signalfloor|gen_ai)\./, ""), show(value)]);
  }
  if (span.attributes["signalfloor.recovered_from_text"] === true) {
    pairs.push(["recovered_from_text", "true"]);
  }
  return pairs;
}

function show(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.map(show).join(", ") : "none";
  if (typeof value === "number" && !Number.isInteger(value)) return value.toFixed(3);
  if (typeof value === "object" && value !== null) return JSON.stringify(value);
  return String(value);
}
