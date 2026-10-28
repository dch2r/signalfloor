import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Run } from "@/lib/api";

import { CompareForm } from "./CompareForm";

function run(id: string, name: string): Run {
  return { id, name, labels: {}, created_at: "2026-10-28T00:00:00Z", n_cases: 100, mean_score: 0.5 };
}

describe("CompareForm", () => {
  it("compares the newest run against the one before by default", () => {
    render(<CompareForm runs={[run("new", "v2"), run("old", "v1"), run("older", "v0")]} />);

    const baseline = screen.getByLabelText("Baseline") as HTMLSelectElement;
    const candidate = screen.getByLabelText("Candidate") as HTMLSelectElement;
    expect(baseline.value).toBe("old");
    expect(candidate.value).toBe("new");
    expect(baseline.name).toBe("baseline");
    expect(candidate.name).toBe("candidate");
    expect(screen.getByRole("button", { name: "Compare" }).closest("form")?.getAttribute("action")).toBe(
      "/compare",
    );
  });

  it("is hidden with fewer than two runs", () => {
    const { container } = render(<CompareForm runs={[run("only", "v1")]} />);

    expect(container.innerHTML).toBe("");
  });
});
