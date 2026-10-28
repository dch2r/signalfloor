import { describe, expect, it } from "vitest";

import { createApi, type Run } from "./api";

const RUN: Run = {
  id: "71d66808-fee6-4667-bfa2-bed953fdb5f1",
  name: "agent v1",
  labels: { prompt: "v1" },
  created_at: "2026-10-28T17:52:14.490714Z",
  n_cases: 100,
  mean_score: 0.155,
};

function respond(status: number, body: unknown): typeof fetch {
  return async () =>
    new Response(JSON.stringify(body), {
      status,
      headers: { "content-type": "application/json" },
    });
}

describe("createApi", () => {
  it("returns the runs", async () => {
    const api = createApi("http://api", respond(200, [RUN]));

    expect(await api.listRuns()).toEqual({ ok: true, data: [RUN] });
  });

  it("asks for the limit it was given", async () => {
    let url = "";
    const api = createApi("http://api", async (input) => {
      url = input instanceof Request ? input.url : String(input);
      return new Response("[]", { headers: { "content-type": "application/json" } });
    });

    await api.listRuns(5);

    expect(url).toBe("http://api/runs?limit=5");
  });

  it("explains an error response", async () => {
    const api = createApi("http://api", respond(422, { detail: "label filter must look like key=value" }));

    expect(await api.listRuns()).toEqual({
      ok: false,
      message: "The API answered 422: label filter must look like key=value",
    });
  });

  it("shows structured error details as JSON", async () => {
    const api = createApi("http://api", respond(422, { detail: [{ msg: "bad" }] }));

    const result = await api.listRuns();

    expect(result.ok || result.message).toBe('The API answered 422: [{"msg":"bad"}]');
  });

  it("handles an error with no details", async () => {
    const api = createApi("http://api", respond(500, "oops"));

    const result = await api.listRuns();

    expect(result.ok || result.message).toBe("The API answered 500: no details");
  });

  it("says so when the server is down", async () => {
    const api = createApi("http://localhost:1", async () => {
      throw new TypeError("fetch failed");
    });

    const result = await api.listRuns();

    expect(result.ok || result.message).toBe(
      "Can't reach the signalfloor API at http://localhost:1. Is signalfloor-server running?",
    );
  });
});

describe("compare calls", () => {
  function recordUrls() {
    const urls: string[] = [];
    const fetchImpl: typeof fetch = async (input) => {
      urls.push(input instanceof Request ? input.url : String(input));
      return new Response("{}", { headers: { "content-type": "application/json" } });
    };
    return { urls, api: createApi("http://api", fetchImpl) };
  }

  it("fetches one run", async () => {
    const { urls, api } = recordUrls();
    await api.getRun("r1");
    expect(urls).toEqual(["http://api/runs/r1"]);
  });

  it("compares with a fixed seed so reloads show the same interval", async () => {
    const { urls, api } = recordUrls();
    await api.compareRuns("a", "b");
    expect(urls).toEqual(["http://api/runs/a/compare/b?seed=0"]);
  });

  it("asks for the case diff", async () => {
    const { urls, api } = recordUrls();
    await api.diffRuns("a", "b", 5);
    expect(urls).toEqual(["http://api/runs/a/diff/b?limit=5"]);
  });
});
