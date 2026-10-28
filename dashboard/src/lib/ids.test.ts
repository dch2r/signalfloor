import { describe, expect, it } from "vitest";

import { isRunId } from "./ids";

describe("isRunId", () => {
  it("accepts a uuid and rejects anything else", () => {
    expect(isRunId("71d66808-fee6-4667-bfa2-bed953fdb5f1")).toBe(true);
    expect(isRunId("71D66808-FEE6-4667-BFA2-BED953FDB5F1")).toBe(true);
    expect(isRunId("nope")).toBe(false);
    expect(isRunId(undefined)).toBe(false);
    expect(isRunId(["71d66808-fee6-4667-bfa2-bed953fdb5f1"])).toBe(false);
  });
});
