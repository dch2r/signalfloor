import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CaseDiffTable } from "./CaseDiffTable";

describe("CaseDiffTable", () => {
  it("shows each case with its change", () => {
    render(
      <CaseDiffTable
        title="Biggest drops"
        empty="none"
        cases={[
          {
            case_id: "5a8c7595554299585d9e36b6",
            baseline_score: 1,
            candidate_score: 0,
            delta: -1,
            baseline_trace_id: null,
            candidate_trace_id: null,
          },
        ]}
      />,
    );

    const row = screen.getAllByRole("row")[1];
    expect(within(row).getByText("5a8c7595554299585d9e36b6")).toBeTruthy();
    expect(within(row).getByText("1.000")).toBeTruthy();
    expect(within(row).getByText("-1.000").className).toContain("text-bad");
  });

  it("says so when there are no cases", () => {
    render(<CaseDiffTable title="Biggest gains" empty="No case got better." cases={[]} />);

    expect(screen.getByText("No case got better.")).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
