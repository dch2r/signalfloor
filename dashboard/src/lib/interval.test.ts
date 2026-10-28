import { describe, expect, it } from "vitest";

import { axisExtent, toPercent } from "./interval";

describe("interval axis", () => {
  it("leaves room past the largest value on either side", () => {
    expect(axisExtent([-0.2, 0.1])).toBeCloseTo(0.23);
    expect(axisExtent([0.01, 0.16, 0.08])).toBeCloseTo(0.184);
  });

  it("has a usable axis when everything is zero", () => {
    expect(axisExtent([0, 0])).toBe(1);
  });

  it("puts zero in the middle", () => {
    expect(toPercent(0, 0.5)).toBe(50);
    expect(toPercent(-0.5, 0.5)).toBe(0);
    expect(toPercent(0.25, 0.5)).toBe(75);
  });

  it("keeps values on the axis", () => {
    expect(toPercent(2, 1)).toBe(100);
    expect(toPercent(-2, 1)).toBe(0);
  });
});
