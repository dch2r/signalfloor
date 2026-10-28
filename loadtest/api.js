// Load test for the signalfloor API with k6 (https://k6.io).
//
//   k6 run -e API_URL=http://localhost:8000 loadtest/api.js
//   k6 run -e PROFILE=stress --out csv=loadtest/results.csv loadtest/api.js
//
// Four kinds of traffic run at the same time, each at a fixed rate. Fixed arrival rates matter:
// if each virtual user waited for its last response before sending the next request, a slow
// server would quietly receive less traffic and its latency would look better than it is.

import http from "k6/http";
import { check } from "k6";

const API = __ENV.API_URL || "http://localhost:8000";
const DURATION = __ENV.DURATION || "1m";
// steady: a fixed, realistic mix. stress: comparisons and browsing ramp up until something gives.
const PROFILE = __ENV.PROFILE || "steady";
const JSON_HEADERS = { headers: { "content-type": "application/json" } };

function scenario(exec, rate, vus) {
  return {
    executor: "constant-arrival-rate",
    exec,
    rate,
    timeUnit: "1s",
    duration: DURATION,
    preAllocatedVUs: vus,
    maxVUs: vus * 4,
  };
}

function ramp(exec, from, to, vus) {
  return {
    executor: "ramping-arrival-rate",
    exec,
    startRate: from,
    timeUnit: "1s",
    stages: [{ target: to, duration: __ENV.DURATION || "3m" }],
    preAllocatedVUs: vus,
    maxVUs: vus * 4,
  };
}

const PROFILES = {
  steady: {
    // People looking at the dashboard: list runs, open one, open a diff.
    browse: scenario("browse", 20, 10),
    // Comparisons are the expensive request: a paired bootstrap on every call.
    compare: scenario("compare", 5, 10),
    // Agents sending traces as they run.
    ingest: scenario("ingest", 50, 20),
    // Eval runs being uploaded.
    upload: scenario("upload", 1, 2),
  },
  stress: {
    browse: ramp("browse", 20, 400, 100),
    compare: ramp("compare", 5, 100, 100),
    ingest: scenario("ingest", 50, 20),
  },
};

export const options = {
  scenarios: PROFILES[PROFILE],
  // Per scenario limits. These also make k6 report each scenario's numbers separately.
  thresholds: {
    http_req_failed: ["rate<0.01"],
    "http_req_duration{scenario:browse}": ["p(95)<1000"],
    "http_req_duration{scenario:compare}": ["p(95)<2000"],
    "http_req_duration{scenario:ingest}": ["p(95)<1000"],
    "http_req_duration{scenario:upload}": ["p(95)<2000"],
  },
};

function cases(n, scoreOf) {
  return Array.from({ length: n }, (_, i) => ({ id: `q${i}`, score: scoreOf(i) }));
}

function uploadRun(name, n, scoreOf) {
  const response = http.post(
    `${API}/runs`,
    JSON.stringify({ name, labels: { loadtest: "yes" }, cases: cases(n, scoreOf) }),
    JSON_HEADERS,
  );
  check(response, { "upload is 201": (r) => r.status === 201 });
  return response.json("id");
}

// Two runs of 500 cases each, about the size of a real eval set.
export function setup() {
  return {
    baseline: uploadRun("load baseline", 500, (i) => (i % 3 === 0 ? 0 : 1)),
    candidate: uploadRun("load candidate", 500, (i) => (i % 4 === 0 ? 0 : 1)),
  };
}

export function browse(runs) {
  const list = http.get(`${API}/runs?limit=20`, { tags: { name: "list runs" } });
  check(list, { "list is 200": (r) => r.status === 200 });
  http.get(`${API}/runs/${runs.candidate}`, { tags: { name: "get run" } });
  const diff = http.get(`${API}/runs/${runs.baseline}/diff/${runs.candidate}`, {
    tags: { name: "diff" },
  });
  check(diff, { "diff is 200": (r) => r.status === 200 });
}

export function compare(runs) {
  const response = http.get(`${API}/runs/${runs.baseline}/compare/${runs.candidate}?seed=0`, {
    tags: { name: "compare" },
  });
  check(response, { "compare is 200": (r) => r.status === 200 });
}

function hex(length) {
  let out = "";
  for (let i = 0; i < length; i++) out += Math.floor(Math.random() * 16).toString(16);
  return out;
}

// One agent case: a root span and four children, in OTLP JSON.
export function ingest() {
  const traceId = hex(32);
  const root = hex(16);
  const start = Date.now() * 1e6;
  const spans = [{ traceId, spanId: root, name: "eval case" }];
  for (let i = 0; i < 4; i++) {
    spans.push({ traceId, spanId: hex(16), parentSpanId: root, name: i % 2 ? "chat" : "search" });
  }
  for (const span of spans) {
    span.startTimeUnixNano = String(start);
    span.endTimeUnixNano = String(start + 1e9);
    span.attributes = [{ key: "signalfloor.query", value: { stringValue: "load test" } }];
  }
  const body = JSON.stringify({
    resourceSpans: [
      {
        resource: { attributes: [{ key: "service.name", value: { stringValue: "load" } }] },
        scopeSpans: [{ spans }],
      },
    ],
  });
  const response = http.post(`${API}/v1/traces`, body, { ...JSON_HEADERS, tags: { name: "ingest" } });
  check(response, { "ingest is 200": (r) => r.status === 200 });
}

export function upload() {
  uploadRun(`load upload ${hex(6)}`, 200, () => Math.random());
}

// A markdown table for the GitHub job summary, plus k6's usual text on standard output.
export function handleSummary(data) {
  const rows = ["browse", "compare", "ingest", "upload"].map((name) => {
    const d = data.metrics[`http_req_duration{scenario:${name}}`];
    const v = d ? d.values : {};
    const ms = (x) => (x === undefined ? "n/a" : `${x.toFixed(0)} ms`);
    return `| ${name} | ${ms(v.med)} | ${ms(v["p(95)"])} | ${ms(v.max)} |`;
  });
  const failed = data.metrics.http_req_failed.values.rate;
  const rate = data.metrics.http_reqs.values.rate;
  const markdown = [
    "## Load test",
    "",
    `${rate.toFixed(0)} requests per second in total, ${(failed * 100).toFixed(2)}% failed.`,
    "",
    "| Scenario | Median | p95 | Max |",
    "|---|---|---|---|",
    ...rows,
    "",
  ].join("\n");
  return { stdout: markdown, "loadtest/summary.md": markdown };
}
