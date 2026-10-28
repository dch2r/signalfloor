import { describe, expect, it } from "vitest";

import { formatCount, formatDate, formatScore } from "./format";

describe("format", () => {
  it("shows dates in UTC", () => {
    expect(formatDate("2026-10-28T17:52:14.490714Z")).toBe("Oct 28, 2026, 5:52 PM UTC");
  });

  it("shows scores to three places", () => {
    expect(formatScore(0.15500775613275614)).toBe("0.155");
    expect(formatScore(1)).toBe("1.000");
  });

  it("groups thousands", () => {
    expect(formatCount(100000)).toBe("100,000");
  });
});
