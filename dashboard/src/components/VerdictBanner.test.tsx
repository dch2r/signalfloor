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
    ...overrides,
  };
}

describe("VerdictBanner", () => {
  it.each([
    ["regression", "Real regression"],
    ["improvement", "Real improvement"],
    ["no_change", "No real change"],
    ["something_new", "No real change"],
  ])("shows %s as %s", (verdict, title) => {
    render(<VerdictBanner comparison={comparison({ verdict })} />);

    expect(screen.getByText(title)).toBeTruthy();
  });

  it("shows the numbers", () => {
    render(<VerdictBanner comparison={comparison({})} />);

    expect(screen.getByText("0.155")).toBeTruthy();
    expect(screen.getByText("0.238")).toBeTruthy();
    expect(screen.getByText("+0.083")).toBeTruthy();
    expect(screen.getByText("95% interval")).toBeTruthy();
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
        comparison={comparison({ verdict: "no_change", delta: 0.01, ci_low: -0.03, ci_high: 0.05 })}
      />,
    );

    const bar = screen.getByTestId("interval");
    const left = parseFloat(bar.style.left);
    expect(left).toBeLessThan(50);
    expect(left + parseFloat(bar.style.width)).toBeGreaterThan(50);
  });
});
