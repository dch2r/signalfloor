import Link from "next/link";
import { Suspense } from "react";

import { ErrorNotice } from "@/components/ErrorNotice";
import { TraceView } from "@/components/TraceView";
import { type Case, createApi, type Run } from "@/lib/api";
import { formatDelta, formatScore } from "@/lib/format";
import { isRunId } from "@/lib/ids";

type Params = Promise<{ caseId: string }>;
type SearchParams = Promise<Record<string, string | string[] | undefined>>;

/** One case from both runs side by side, so you can see what the candidate did differently. */
export default function CaseComparePage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  return (
    <Suspense fallback={<div className="h-48 animate-pulse rounded-lg bg-subtle" />}>
      <CaseCompare params={params} searchParams={searchParams} />
    </Suspense>
  );
}

async function CaseCompare({ params, searchParams }: { params: Params; searchParams: SearchParams }) {
  const { caseId } = await params;
  const { baseline: baselineId, candidate: candidateId } = await searchParams;
  if (!isRunId(baselineId) || !isRunId(candidateId)) {
    return <ErrorNotice message="Open a case from the compare page." />;
  }

  const api = createApi();
  const [baselineRun, candidateRun, baselineCase, candidateCase] = await Promise.all([
    api.getRun(baselineId),
    api.getRun(candidateId),
    api.getCase(baselineId, caseId),
    api.getCase(candidateId, caseId),
  ]);
  if (!baselineRun.ok) return <ErrorNotice message={baselineRun.message} />;
  if (!candidateRun.ok) return <ErrorNotice message={candidateRun.message} />;
  if (!baselineCase.ok) return <ErrorNotice message={baselineCase.message} />;
  if (!candidateCase.ok) return <ErrorNotice message={candidateCase.message} />;

  const delta = candidateCase.data.score - baselineCase.data.score;
  return (
    <>
      <Link
        href={`/compare?baseline=${baselineId}&candidate=${candidateId}`}
        className="text-sm text-muted hover:text-foreground"
      >
        ← Comparison
      </Link>
      <h1 className="mt-2 text-xl font-semibold">
        Case <span className="font-mono text-base">{caseId}</span>
      </h1>
      <p className="mt-1 text-sm text-muted">
        Score {formatScore(baselineCase.data.score)} → {formatScore(candidateCase.data.score)} (
        <span className={delta < 0 ? "text-bad" : delta > 0 ? "text-good" : ""}>
          {formatDelta(delta)}
        </span>
        )
      </p>
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <CaseColumn role="Baseline" run={baselineRun.data} result={baselineCase.data} />
        <CaseColumn role="Candidate" run={candidateRun.data} result={candidateCase.data} />
      </div>
    </>
  );
}

function CaseColumn({ role, run, result }: { role: string; run: Run; result: Case }) {
  return (
    <section className="rounded-lg border border-line p-4">
      <p className="text-sm text-muted">{role}</p>
      <h2 className="font-medium">{run.name}</h2>
      <p className="text-sm">Score {formatScore(result.score)}</p>
      <div className="mt-4">
        {result.trace_id ? (
          <TraceView spans={result.spans} />
        ) : (
          <p className="text-sm text-muted">
            This run was uploaded without traces. Run the eval with --otlp-endpoint to record
            them.
          </p>
        )}
      </div>
    </section>
  );
}
