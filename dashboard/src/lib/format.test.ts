import { describe, expect, it } from "vitest";

import { formatCount, formatDate, formatDelta, formatPercent, formatScore } from "./format";

describe("format", () => {
  it("shows dates in UTC", () => {
    expect(formatDate("2026-10-28T17:52:14.490714Z")).toBe("Oct 28, 2026, 5:52 PM UTC");
  });

  it("shows scores to three places", () => {
    expect(formatScore(0.15500775613275614)).toBe("0.155");
    expect(formatScore(1)).toBe("1.000");
  });

  it("signs changes", () => {
    expect(formatDelta(0.08349213139801376)).toBe("+0.083");
    expect(formatDelta(-0.105)).toBe("-0.105");
  });

  it("does not sign a change that rounds to zero", () => {
    expect(formatDelta(0)).toBe("0.000");
    expect(formatDelta(-0.0001)).toBe("0.000");
  });

  it("shows shares as percentages", () => {
    expect(formatPercent(0.0362)).toBe("3.6%");
    expect(formatPercent(1)).toBe("100.0%");
  });

  it("groups thousands", () => {
    expect(formatCount(100000)).toBe("100,000");
  });
});
