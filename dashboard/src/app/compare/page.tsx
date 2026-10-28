import Link from "next/link";
import { Suspense } from "react";

import { CaseDiffTable } from "@/components/CaseDiffTable";
import { ErrorNotice } from "@/components/ErrorNotice";
import { LeftOutNotice } from "@/components/LeftOutNotice";
import { VerdictBanner } from "@/components/VerdictBanner";
import { createApi, type Run } from "@/lib/api";
import { isRunId } from "@/lib/ids";

type SearchParams = Promise<Record<string, string | string[] | undefined>>;

export default function ComparePage({ searchParams }: { searchParams: SearchParams }) {
  return (
    <>
      <Link href="/" className="text-sm text-muted hover:text-foreground">
        ← Runs
      </Link>
      <h1 className="mt-2 text-xl font-semibold">Compare runs</h1>
      {/* The runs come from the URL, which is only known at request time. */}
      <Suspense fallback={<div className="mt-6 h-48 animate-pulse rounded-lg bg-subtle" />}>
        <Comparison searchParams={searchParams} />
      </Suspense>
    </>
  );
}

async function Comparison({ searchParams }: { searchParams: SearchParams }) {
  const params = await searchParams;
  const baselineId = params.baseline;
  const candidateId = params.candidate;
  if (!isRunId(baselineId) || !isRunId(candidateId)) {
    return <Failed message="Pick a baseline and a candidate run on the Runs page." />;
  }

  const api = createApi();
  const [baseline, candidate, comparison, diff] = await Promise.all([
    api.getRun(baselineId),
    api.getRun(candidateId),
    api.compareRuns(baselineId, candidateId),
    api.diffRuns(baselineId, candidateId),
  ]);
  if (!baseline.ok) return <Failed message={baseline.message} />;
  if (!candidate.ok) return <Failed message={candidate.message} />;
  if (!comparison.ok) return <Failed message={comparison.message} />;
  if (!diff.ok) return <Failed message={diff.message} />;

  const d = diff.data;
  return (
    <div className="mt-6 space-y-8">
      <div className="grid gap-3 text-sm sm:grid-cols-2">
        <RunCard role="Baseline" run={baseline.data} />
        <RunCard role="Candidate" run={candidate.data} />
      </div>

      <LeftOutNotice diff={d} />

      <VerdictBanner comparison={comparison.data} />

      <p className="text-sm">
        Of {d.n_shared} shared cases, <strong className="text-bad">{d.n_worse} got worse</strong>,{" "}
        <strong className="text-good">{d.n_better} got better</strong> and {d.n_same} stayed the
        same.
      </p>

      <div className="grid gap-8 lg:grid-cols-2">
        <CaseDiffTable
          title="Biggest drops"
          cases={d.worst}
          empty="No case got worse."
          runs={{ baselineId, candidateId }}
        />
        <CaseDiffTable
          title="Biggest gains"
          cases={d.best}
          empty="No case got better."
          runs={{ baselineId, candidateId }}
        />
      </div>
    </div>
  );
}

function Failed({ message }: { message: string }) {
  return (
    <div className="mt-6">
      <ErrorNotice message={message} />
    </div>
  );
}

function RunCard({ role, run }: { role: string; run: Run }) {
  return (
    <div className="rounded-lg border border-line p-3">
      <p className="text-muted">{role}</p>
      <p className="font-medium">{run.name}</p>
      <p className="mt-1 flex flex-wrap gap-1">
        {Object.entries(run.labels).map(([key, value]) => (
          <span key={key} className="rounded bg-subtle px-1.5 py-0.5 font-mono text-xs">
            {key}={value}
          </span>
        ))}
      </p>
    </div>
  );
}
