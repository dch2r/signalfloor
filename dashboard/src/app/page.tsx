import { Suspense } from "react";

import { ErrorNotice } from "@/components/ErrorNotice";
import { RunsTable, RunsTableSkeleton } from "@/components/RunsTable";
import { createApi } from "@/lib/api";

export default function RunsPage() {
  return (
    <>
      <h1 className="text-xl font-semibold">Runs</h1>
      <p className="mt-1 text-sm text-muted">Every eval run uploaded to the server, newest first.</p>
      <div className="mt-6">
        {/* Runs change all the time, so they are fetched on every request, not cached. */}
        <Suspense fallback={<RunsTableSkeleton />}>
          <Runs />
        </Suspense>
      </div>
    </>
  );
}

async function Runs() {
  const result = await createApi().listRuns();
  return result.ok ? <RunsTable runs={result.data} /> : <ErrorNotice message={result.message} />;
}
