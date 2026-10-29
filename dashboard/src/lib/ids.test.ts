import { describe, expect, it } from "vitest";

import { isRunId, parseMargin } from "./ids";

describe("isRunId", () => {
  it("accepts a uuid and rejects anything else", () => {
    expect(isRunId("71d66808-fee6-4667-bfa2-bed953fdb5f1")).toBe(true);
    expect(isRunId("71D66808-FEE6-4667-BFA2-BED953FDB5F1")).toBe(true);
    expect(isRunId("nope")).toBe(false);
    expect(isRunId(undefined)).toBe(false);
    expect(isRunId(["71d66808-fee6-4667-bfa2-bed953fdb5f1"])).toBe(false);
  });
});

describe("parseMargin", () => {
  it("reads a margin, or none", () => {
    expect(parseMargin("0.02")).toBe(0.02);
    expect(parseMargin("0")).toBe(0);
    expect(parseMargin(undefined)).toBeUndefined();
    expect(parseMargin("")).toBeUndefined();
  });

  it("rejects margins it can't use", () => {
    expect(parseMargin("-0.1")).toBeNull();
    expect(parseMargin("abc")).toBeNull();
    expect(parseMargin("Infinity")).toBeNull();
    expect(parseMargin(["0.1", "0.2"])).toBeNull();
  });
});
