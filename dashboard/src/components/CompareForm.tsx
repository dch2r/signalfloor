import type { Run } from "@/lib/api";
import { formatScore } from "@/lib/format";

/**
 * Pick a baseline and a candidate. A plain GET form, so it works without any JavaScript and the
 * comparison gets a URL that can be shared.
 */
export function CompareForm({ runs }: { runs: Run[] }) {
  if (runs.length < 2) return null;
  // Runs are newest first. The usual question is whether the newest run beat the one before.
  const [newest, previous] = runs;

  return (
    <form action="/compare" method="get" className="mt-8 rounded-lg border border-line p-4">
      <h2 className="font-medium">Compare two runs</h2>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <RunPicker name="baseline" label="Baseline" runs={runs} selected={previous.id} />
        <RunPicker name="candidate" label="Candidate" runs={runs} selected={newest.id} />
      </div>
      <button
        type="submit"
        className="mt-4 rounded-md bg-foreground px-4 py-2 text-sm font-medium text-background hover:opacity-90"
      >
        Compare
      </button>
    </form>
  );
}

function RunPicker({
  name,
  label,
  runs,
  selected,
}: {
  name: string;
  label: string;
  runs: Run[];
  selected: string;
}) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <select
        name={name}
        defaultValue={selected}
        className="mt-1 block w-full rounded-md border border-line bg-background px-2 py-1.5"
      >
        {runs.map((run) => (
          <option key={run.id} value={run.id}>
            {run.name} ({run.n_cases} cases, mean {formatScore(run.mean_score)})
          </option>
        ))}
      </select>
    </label>
  );
}
