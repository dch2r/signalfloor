import type { RunDiff } from "@/lib/api";

/**
 * Says which cases the comparison left out, when the two runs don't have the same questions.
 * The verdict only covers the shared cases, and the reader has to know that before trusting it.
 */
export function LeftOutNotice({ diff }: { diff: RunDiff }) {
  const parts = [
    leftOut(diff.only_in_baseline, "the baseline"),
    leftOut(diff.only_in_candidate, "the candidate"),
  ].filter(Boolean);
  if (parts.length === 0) return null;

  return (
    <div role="note" className="rounded-lg border border-line bg-subtle p-4 text-sm">
      <p className="font-medium">These runs don&apos;t have the same cases.</p>
      <p className="mt-1 text-muted">
        {parts.join(" and ")} {diff.only_in_baseline + diff.only_in_candidate === 1 ? "is" : "are"}{" "}
        left out. Everything below uses
        the {diff.n_shared} {diff.n_shared === 1 ? "case" : "cases"} both runs share.
      </p>
    </div>
  );
}

function leftOut(count: number, run: string): string {
  if (count === 0) return "";
  return `${count} ${count === 1 ? "case" : "cases"} only in ${run}`;
}
