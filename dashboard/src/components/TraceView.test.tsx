import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { span } from "@/lib/test-spans";

import { formatDuration, TraceView } from "./TraceView";

describe("TraceView", () => {
  it("shows each span with its duration and attributes", () => {
    render(
      <TraceView
        spans={[
          span("eval case", null, 0, 8981),
          span("execute_tool search", "eval case", 3424, 36, {
            attributes: { "signalfloor.query": "woman who portrayed Corliss Archer" },
          }),
        ]}
      />,
    );

    expect(screen.getByText("eval case")).toBeTruthy();
    expect(screen.getByText("9.0 s")).toBeTruthy();
    expect(screen.getByText("36 ms")).toBeTruthy();
    expect(screen.getByText("woman who portrayed Corliss Archer")).toBeTruthy();
    expect(screen.getAllByTestId("span-bar")).toHaveLength(2);
  });

  it("marks failed spans and shows why", () => {
    render(
      <TraceView
        spans={[
          span("execute_tool calculator", null, 0, 1, {
            status: "error",
            status_message: "model called a tool that does not exist",
          }),
        ]}
      />,
    );

    expect(screen.getByText("execute_tool calculator").className).toContain("text-bad");
    expect(screen.getByText("model called a tool that does not exist")).toBeTruthy();
  });

  it("says so when no spans arrived", () => {
    render(<TraceView spans={[]} />);

    expect(screen.getByText("No spans have arrived for this trace.")).toBeTruthy();
  });
});

describe("formatDuration", () => {
  it("picks a readable unit", () => {
    expect(formatDuration(8981)).toBe("9.0 s");
    expect(formatDuration(36.4)).toBe("36 ms");
    expect(formatDuration(0.25)).toBe("250 µs");
  });
});
