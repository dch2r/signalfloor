import type { Span } from "@/lib/api";
import { layoutTrace, readableAttributes } from "@/lib/trace";

/** A trace as an indented list of spans, each with a bar on a shared timeline. */
export function TraceView({ spans }: { spans: Span[] }) {
  const rows = layoutTrace(spans);
  if (rows.length === 0) {
    return <p className="text-sm text-muted">No spans have arrived for this trace.</p>;
  }

  return (
    <ol className="space-y-3">
      {rows.map(({ span, depth, offset, width }) => {
        const failed = span.status === "error";
        return (
          <li key={span.span_id} style={{ paddingLeft: `${depth * 1}rem` }}>
            <div className="flex items-baseline justify-between gap-3 text-sm">
              <span className={`font-medium ${failed ? "text-bad" : ""}`}>{span.name}</span>
              <span className="shrink-0 font-mono text-xs tabular-nums text-muted">
                {formatDuration(span.duration_ms)}
              </span>
            </div>
            <div className="relative mt-1 h-1.5 rounded bg-subtle">
              <div
                data-testid="span-bar"
                className={`absolute h-full rounded ${failed ? "bg-bad" : "bg-foreground/50"}`}
                style={{ left: `${offset}%`, width: `${width}%` }}
              />
            </div>
            {failed && span.status_message && (
              <p className="mt-1 text-xs text-bad">{span.status_message}</p>
            )}
            <dl className="mt-1 space-y-0.5 text-xs">
              {readableAttributes(span).map(([key, value]) => (
                <div key={key} className="flex gap-2">
                  <dt className="shrink-0 text-muted">{key}</dt>
                  <dd className="break-words font-mono">{value}</dd>
                </div>
              ))}
            </dl>
          </li>
        );
      })}
    </ol>
  );
}

export function formatDuration(ms: number): string {
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  if (ms >= 1) return `${Math.round(ms)} ms`;
  return `${(ms * 1000).toFixed(0)} µs`;
}
