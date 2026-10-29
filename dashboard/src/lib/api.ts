import "server-only";

import createClient from "openapi-fetch";

import type { components, paths } from "./api-types";

export type Run = components["schemas"]["RunOut"];
export type Comparison = components["schemas"]["ComparisonOut"];
export type RunDiff = components["schemas"]["RunDiffOut"];
export type CaseDiff = components["schemas"]["CaseDiff"];
export type Case = components["schemas"]["CaseOut"];
export type Span = components["schemas"]["SpanOut"];

export const API_URL = process.env.SIGNALFLOOR_API_URL ?? "http://127.0.0.1:8000";

export type Result<T> = { ok: true; data: T } | { ok: false; message: string };

export function createApi(
  baseUrl: string = API_URL,
  fetchImpl: typeof fetch = fetch,
  // Read on the server only. This module is server-only, so the key never reaches a browser.
  apiKey: string | undefined = process.env.SIGNALFLOOR_API_KEY,
) {
  const client = createClient<paths>({
    baseUrl,
    fetch: fetchImpl,
    headers: apiKey ? { Authorization: `Bearer ${apiKey}` } : undefined,
  });

  // Errors are returned, not thrown. In production Next.js hides the message of an error thrown
  // in a server component, and "the API is down" is something the user needs to read.
  async function call<T>(
    request: () => Promise<{ data?: T; error?: unknown; response: Response }>,
  ): Promise<Result<T>> {
    try {
      const { data, error, response } = await request();
      if (data !== undefined) return { ok: true, data };
      return { ok: false, message: `The API answered ${response.status}: ${detail(error)}` };
    } catch {
      return {
        ok: false,
        message: `Can't reach the signalfloor API at ${baseUrl}. Is signalfloor-server running?`,
      };
    }
  }

  return {
    listRuns: (limit = 100) =>
      call(() => client.GET("/runs", { params: { query: { limit } } })),
    getRun: (runId: string) =>
      call(() => client.GET("/runs/{run_id}", { params: { path: { run_id: runId } } })),
    // A fixed seed so the interval doesn't shift a little every time the page is reloaded.
    // Runs with different questions are compared on the questions they share. The compare page
    // says how many were left out, using the counts from diffRuns.
    compareRuns: (baselineId: string, candidateId: string, margin?: number) =>
      call(() =>
        client.GET("/runs/{baseline_id}/compare/{candidate_id}", {
          params: {
            path: { baseline_id: baselineId, candidate_id: candidateId },
            query: { seed: 0, shared_only: true, ...(margin === undefined ? {} : { margin }) },
          },
        }),
      ),
    getCase: (runId: string, caseId: string) =>
      call(() =>
        client.GET("/runs/{run_id}/cases/{case_id}", {
          params: { path: { run_id: runId, case_id: caseId } },
        }),
      ),
    diffRuns: (baselineId: string, candidateId: string, limit = 20) =>
      call(() =>
        client.GET("/runs/{baseline_id}/diff/{candidate_id}", {
          params: {
            path: { baseline_id: baselineId, candidate_id: candidateId },
            query: { limit },
          },
        }),
      ),
  };
}

function detail(error: unknown): string {
  if (error && typeof error === "object" && "detail" in error) {
    const value = (error as { detail: unknown }).detail;
    return typeof value === "string" ? value : JSON.stringify(value);
  }
  return "no details";
}
