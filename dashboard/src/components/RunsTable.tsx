import type { Run } from "@/lib/api";
import { formatCount, formatDate, formatScore } from "@/lib/format";

export function RunsTable({ runs }: { runs: Run[] }) {
  if (runs.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-line p-8 text-center text-muted">
        <p className="font-medium text-foreground">No runs yet</p>
        <p className="mt-2 text-sm">
          Upload one with <code className="font-mono">POST /runs</code>. The server README shows
          how.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-line">
      <table className="w-full text-left text-sm">
        <thead className="bg-subtle text-muted">
          <tr>
            <th className="px-4 py-2 font-medium">Name</th>
            <th className="px-4 py-2 font-medium">Labels</th>
            <th className="px-4 py-2 text-right font-medium">Cases</th>
            <th className="px-4 py-2 text-right font-medium">Mean score</th>
            <th className="px-4 py-2 font-medium">Uploaded</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run) => (
            <tr key={run.id} className="border-t border-line">
              <td className="px-4 py-2 font-medium">{run.name}</td>
              <td className="px-4 py-2">
                <div className="flex flex-wrap gap-1">
                  {Object.entries(run.labels).map(([key, value]) => (
                    <span key={key} className="rounded bg-subtle px-1.5 py-0.5 font-mono text-xs">
                      {key}={value}
                    </span>
                  ))}
                </div>
              </td>
              <td className="px-4 py-2 text-right tabular-nums">{formatCount(run.n_cases)}</td>
              <td className="px-4 py-2 text-right tabular-nums">{formatScore(run.mean_score)}</td>
              <td className="whitespace-nowrap px-4 py-2 text-muted">
                {formatDate(run.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RunsTableSkeleton() {
  return (
    <div className="space-y-2" aria-busy="true" aria-label="Loading runs">
      {[0, 1, 2].map((i) => (
        <div key={i} className="h-10 animate-pulse rounded bg-subtle" />
      ))}
    </div>
  );
}
