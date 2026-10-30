import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Comparison } from "@/lib/api";

import { VerdictBanner } from "./VerdictBanner";

function comparison(overrides: Partial<Comparison>): Comparison {
  return {
    baseline_id: "a",
    candidate_id: "b",
    // The real comparison of the agent's v1 and v2 prompts.
    baseline_mean: 0.15500775613275614,
    candidate_mean: 0.2384998875307699,
    delta: 0.08349213139801376,
    ci_low: 0.011545259740259751,
    ci_high: 0.15946885090399796,
    confidence: 0.95,
    n_cases: 100,
    n_resamples: 10000,
    verdict: "improvement",
    largest_drop_not_ruled_out: 0.025,
    // Made up so the verdict holds. With the real bounds this comparison is inconclusive.
    bound_low: 0.004,
    bound_high: 0.190,
    max_case_drop: 1,
    missing_cases: 0,
    no_change_drop: 0.048,
    ...overrides,
  };
}

describe("VerdictBanner", () => {
  it.each([
    ["regression", "Regression"],
    ["improvement", "Improvement"],
    ["inconclusive", "Inconclusive"],
    ["something_new", "Inconclusive"],
  ])("shows %s as %s", (verdict, title) => {
    render(<VerdictBanner comparison={comparison({ verdict })} />);

    expect(screen.getByText(title)).toBeTruthy();
  });

  it("shows the numbers", () => {
    render(<VerdictBanner comparison={comparison({})} />);

    expect(screen.getByText("0.155")).toBeTruthy();
    expect(screen.getByText("0.238")).toBeTruthy();
    expect(screen.getByText("+0.083")).toBeTruthy();
    expect(screen.getByText("95% bootstrap interval")).toBeTruthy();
    expect(screen.getByText("+0.012 to +0.159")).toBeTruthy();
    expect(screen.getByText(/100 shared cases with 10,000 resamples/)).toBeTruthy();
  });

  it("draws an interval that clears zero for a real change", () => {
    render(<VerdictBanner comparison={comparison({})} />);

    const bar = screen.getByTestId("interval");
    expect(parseFloat(bar.style.left)).toBeGreaterThan(50);
  });

  it("draws an interval across zero when it is noise", () => {
    render(
      <VerdictBanner
        comparison={comparison({ verdict: "inconclusive", delta: 0.01, ci_low: -0.03, ci_high: 0.05 })}
      />,
    );

    const bar = screen.getByTestId("interval");
    const left = parseFloat(bar.style.left);
    expect(left).toBeLessThan(50);
    expect(left + parseFloat(bar.style.width)).toBeGreaterThan(50);
  });
});

describe("VerdictBanner wording", () => {
  it("says an inconclusive result is not the same as no change, and how big a drop is possible", () => {
    render(
      <VerdictBanner
        comparison={comparison({
          verdict: "inconclusive",
          ci_low: -0.1306,
          ci_high: 0.1513,
          largest_drop_not_ruled_out: 0.1306,
        })}
      />,
    );

    expect(screen.getByText(/not the same as no change/)).toBeTruthy();
    expect(screen.getByText("0.131")).toBeTruthy();
    expect(screen.getByText(/can.t be ruled out/)).toBeTruthy();
    expect(screen.queryByTestId("decision")).toBeNull();
  });

  it("doesn't call the interval run to run noise", () => {
    const { container } = render(<VerdictBanner comparison={comparison({ verdict: "regression" })} />);

    expect(container.textContent).not.toContain("between runs");
    expect(container.textContent).toContain("hold at any sample size");
  });

  it("speaks of likelihood, not proof", () => {
    for (const verdict of ["regression", "improvement"]) {
      const { container, unmount } = render(<VerdictBanner comparison={comparison({ verdict })} />);

      expect(container.textContent).toContain("likely");
      expect(container.textContent).not.toMatch(/proven|too large to come from/);
      unmount();
    }
  });

  it("shows the bounds the verdict comes from", () => {
    render(<VerdictBanner comparison={comparison({})} />);

    expect(screen.getByTestId("bounds").textContent).toBe("+0.004 to +0.190");
  });

  it.each([
    [1, "1 case is in only one run."],
    [10, "10 cases are in only one run."],
  ])("explains %i missing cases", (missing, text) => {
    render(<VerdictBanner comparison={comparison({ missing_cases: missing })} />);

    expect(screen.getByTestId("missing-cases").textContent).toContain(text);
  });

  it("says nothing about missing cases when there are none", () => {
    render(<VerdictBanner comparison={comparison({})} />);

    expect(screen.queryByTestId("missing-cases")).toBeNull();
  });

  it.each([
    ["pass", "Pass", "The bounds rule out a drop larger than 0.020."],
    ["fail", "Fail", "The bounds put the drop above 0.020."],
    ["needs_more_evidence", "Needs more evidence", "The data can't tell if the drop is within 0.020."],
  ])("shows the %s decision", (decision, label, text) => {
    render(<VerdictBanner comparison={comparison({ margin: 0.02, decision })} />);

    expect(screen.getByTestId("decision").textContent).toBe(label);
    expect(screen.getByText(new RegExp(text.replace(/[.']/g, ".")))).toBeTruthy();
  });

  it("says how many cases a margin needs when there are too few", () => {
    render(
      <VerdictBanner
        comparison={comparison({ margin: 0.02, decision: "needs_more_evidence", cases_needed: 249 })}
      />,
    );

    expect(screen.getByTestId("cases-needed").textContent).toBe(
      "When nothing changes, a margin of 0.020 needs at least 249 cases. " +
        "With 100, even an unchanged eval can't rule out a drop of 0.048.",
    );
  });

  it.each([
    ["the eval already has enough cases", { cases_needed: 72 }],
    ["the margin is zero", { cases_needed: null }],
    ["the decision is not about evidence", { decision: "pass", cases_needed: 183 }],
  ])("says nothing about case counts when %s", (_, overrides) => {
    render(
      <VerdictBanner
        comparison={comparison({ margin: 0.05, decision: "needs_more_evidence", ...overrides })}
      />,
    );

    expect(screen.queryByTestId("cases-needed")).toBeNull();
  });
});
