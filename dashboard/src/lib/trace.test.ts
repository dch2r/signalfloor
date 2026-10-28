import { describe, expect, it } from "vitest";

import { span } from "./test-spans";
import { layoutTrace, readableAttributes } from "./trace";

describe("layoutTrace", () => {
  it("nests children under their parent in start order", () => {
    // Given out of order, the way they can arrive from the exporter.
    const rows = layoutTrace([
      span("search", "agent", 400, 100),
      span("chat-2", "agent", 500, 500),
      span("root", null, 0, 1000),
      span("chat-1", "agent", 0, 400),
      span("agent", "root", 0, 1000),
    ]);

    expect(rows.map((r) => [r.span.span_id, r.depth])).toEqual([
      ["root", 0],
      ["agent", 1],
      ["chat-1", 2],
      ["search", 2],
      ["chat-2", 2],
    ]);
  });

  it("places spans on the trace timeline", () => {
    const rows = layoutTrace([span("root", null, 0, 1000), span("late", "root", 750, 250)]);

    expect(rows[0]).toMatchObject({ offset: 0, width: 100 });
    expect(rows[1]).toMatchObject({ offset: 75, width: 25 });
  });

  it("keeps very short spans visible", () => {
    const rows = layoutTrace([span("root", null, 0, 10_000), span("fast", "root", 0, 0.01)]);

    expect(rows[1].width).toBe(0.5);
  });

  it("shows spans whose parent never arrived at the top level", () => {
    const rows = layoutTrace([span("orphan", "missing", 0, 10), span("root", null, 5, 10)]);

    expect(rows.map((r) => [r.span.span_id, r.depth])).toEqual([
      ["orphan", 0],
      ["root", 0],
    ]);
  });

  it("does not loop on a span that is its own parent", () => {
    const rows = layoutTrace([span("a", null, 0, 10), span("a", "a", 0, 10)]);

    expect(rows).toHaveLength(1);
  });

  it("handles an empty trace and a trace of zero length", () => {
    expect(layoutTrace([])).toEqual([]);
    expect(layoutTrace([span("a", null, 0, 0)])[0]).toMatchObject({ offset: 0, width: 0.5 });
  });
});

describe("readableAttributes", () => {
  it("drops attributes every span has and shortens the rest", () => {
    const pairs = readableAttributes(
      span("s", null, 0, 1, {
        attributes: {
          "gen_ai.operation.name": "execute_tool",
          "gen_ai.tool.name": "search",
          "signalfloor.query": "woman who portrayed Corliss Archer",
          "signalfloor.titles": ["Meet Corliss Archer", "Kiss and Tell"],
          "gen_ai.usage.input_tokens": 286,
          "signalfloor.score": 0.5,
          "signalfloor.tool_calls": [],
          "signalfloor.recovered_from_text": false,
          "signalfloor.extra": { a: 1 },
          "signalfloor.nothing": null,
        },
      }),
    );

    expect(pairs).toEqual([
      ["query", "woman who portrayed Corliss Archer"],
      ["titles", "Meet Corliss Archer, Kiss and Tell"],
      ["usage.input_tokens", "286"],
      ["score", "0.500"],
      ["tool_calls", "none"],
      ["extra", '{"a":1}'],
    ]);
  });

  it("flags tool calls recovered from text", () => {
    const pairs = readableAttributes(
      span("s", null, 0, 1, { attributes: { "signalfloor.recovered_from_text": true } }),
    );

    expect(pairs).toEqual([["recovered_from_text", "true"]]);
  });
});
