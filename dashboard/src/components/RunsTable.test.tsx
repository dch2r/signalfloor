import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Run } from "@/lib/api";

import { RunsTable } from "./RunsTable";

const runs: Run[] = [
  {
    id: "b",
    name: "agent v2",
    labels: { prompt: "v2", model: "qwen3:1.7b" },
    created_at: "2026-10-28T17:52:14Z",
    n_cases: 1200,
    mean_score: 0.2384998875307699,
  },
  {
    id: "a",
    name: "agent v1",
    labels: {},
    created_at: "2026-10-28T17:50:00Z",
    n_cases: 100,
    mean_score: 0.155,
  },
];

describe("RunsTable", () => {
  it("shows one row per run", () => {
    render(<RunsTable runs={runs} />);

    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    const first = within(rows[0]);
    expect(first.getByText("agent v2")).toBeTruthy();
    expect(first.getByText("prompt=v2")).toBeTruthy();
    expect(first.getByText("model=qwen3:1.7b")).toBeTruthy();
    expect(first.getByText("1,200")).toBeTruthy();
    expect(first.getByText("0.238")).toBeTruthy();
    expect(first.getByText("Oct 28, 2026, 5:52 PM UTC")).toBeTruthy();
  });

  it("explains what to do when there are no runs", () => {
    render(<RunsTable runs={[]} />);

    expect(screen.getByText("No runs yet")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
