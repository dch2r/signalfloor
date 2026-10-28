import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { RunDiff } from "@/lib/api";

import { LeftOutNotice } from "./LeftOutNotice";

function diff(onlyInBaseline: number, onlyInCandidate: number, shared = 20): RunDiff {
  return {
    baseline_id: "a",
    candidate_id: "b",
    n_shared: shared,
    n_worse: 0,
    n_better: 0,
    n_same: shared,
    only_in_baseline: onlyInBaseline,
    only_in_candidate: onlyInCandidate,
    worst: [],
    best: [],
  };
}

describe("LeftOutNotice", () => {
  it("is hidden when both runs have the same cases", () => {
    const { container } = render(<LeftOutNotice diff={diff(0, 0)} />);

    expect(container.innerHTML).toBe("");
  });

  it("says what was left out of a 20 question run against a 100 question run", () => {
    render(<LeftOutNotice diff={diff(0, 80)} />);

    expect(screen.getByRole("note").textContent).toContain(
      "80 cases only in the candidate are left out. Everything below uses the 20 cases both runs share.",
    );
  });

  it("uses the singular for a single case", () => {
    render(<LeftOutNotice diff={diff(1, 0)} />);

    expect(screen.getByRole("note").textContent).toContain("1 case only in the baseline is left out.");
  });

  it("covers cases missing on both sides", () => {
    render(<LeftOutNotice diff={diff(1, 2, 1)} />);

    expect(screen.getByRole("note").textContent).toContain(
      "1 case only in the baseline and 2 cases only in the candidate are left out. Everything below uses the 1 case both runs share.",
    );
  });
});
