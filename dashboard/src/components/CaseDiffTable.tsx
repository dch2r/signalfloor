import Link from "next/link";

import type { CaseDiff } from "@/lib/api";
import { formatDelta, formatScore } from "@/lib/format";

export function CaseDiffTable({
  title,
  cases,
  empty,
  runs,
}: {
  title: string;
  cases: CaseDiff[];
  empty: string;
  runs: { baselineId: string; candidateId: string };
}) {
  const query = `baseline=${runs.baselineId}&candidate=${runs.candidateId}`;
  return (
    <section>
      <h2 className="font-medium">{title}</h2>
      {cases.length === 0 ? (
        <p className="mt-2 text-sm text-muted">{empty}</p>
      ) : (
        <div className="mt-2 overflow-x-auto rounded-lg border border-line">
          <table className="w-full text-left text-sm">
            <thead className="bg-subtle text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Case</th>
                <th className="px-3 py-2 text-right font-medium">Baseline</th>
                <th className="px-3 py-2 text-right font-medium">Candidate</th>
                <th className="px-3 py-2 text-right font-medium">Change</th>
              </tr>
            </thead>
            <tbody>
              {cases.map((c) => (
                <tr key={c.case_id} className="border-t border-line">
                  <td className="max-w-48 truncate px-3 py-2 font-mono text-xs" title={c.case_id}>
                    <Link
                      href={`/compare/${encodeURIComponent(c.case_id)}?${query}`}
                      className="underline decoration-line underline-offset-2 hover:decoration-foreground"
                    >
                      {c.case_id}
                    </Link>
                    {(c.baseline_trace_id || c.candidate_trace_id) && (
                      <span className="ml-1 text-muted" title="Has a trace">
                        ●
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatScore(c.baseline_score)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatScore(c.candidate_score)}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-medium tabular-nums ${
                      c.delta < 0 ? "text-bad" : "text-good"
                    }`}
                  >
                    {formatDelta(c.delta)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
