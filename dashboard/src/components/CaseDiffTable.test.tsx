import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseDiffTable } from "./CaseDiffTable";

const RUNS = { baselineId: "base-id", candidateId: "cand-id" };

describe("CaseDiffTable", () => {
  it("shows each case with its change", () => {
    render(
      <CaseDiffTable
        title="Biggest drops"
        empty="none"
        runs={RUNS}
        cases={[
          {
            case_id: "5a8c7595554299585d9e36b6",
            baseline_score: 1,
            candidate_score: 0,
            delta: -1,
            baseline_trace_id: null,
            candidate_trace_id: "1e25e12afbd6768c9b2686196163c206",
          },
        ]}
      />,
    );

    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("5a8c7595554299585d9e36b6")).toBeTruthy();
    expect(within(row).getByText("1.000")).toBeTruthy();
    expect(within(row).getByText("-1.000").className).toContain("text-bad");
    expect(within(row).getByRole("link").getAttribute("href")).toBe(
      "/compare/5a8c7595554299585d9e36b6?baseline=base-id&candidate=cand-id",
    );
    expect(within(row).getByTitle("Has a trace")).toBeTruthy();
  });

  it("says so when there are no cases", () => {
    render(<CaseDiffTable title="Biggest gains" empty="No case got better." cases={[]} runs={RUNS} />);

    expect(screen.getByText("No case got better.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});

it("escapes case ids in the link and marks cases without traces", () => {
  render(
    <CaseDiffTable
      title="t"
      empty="e"
      runs={RUNS}
      cases={[
        {
          case_id: "a/b c",
          baseline_score: 1,
          candidate_score: 0.5,
          delta: -0.5,
          baseline_trace_id: null,
          candidate_trace_id: null,
        },
      ]}
    />,
  );

  expect(screen.getByRole("link").getAttribute("href")).toBe(
    "/compare/a%2Fb%20c?baseline=base-id&candidate=cand-id",
  );
  expect(screen.queryByTitle("Has a trace")).toBeNull();
});
