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
      <label className="mt-4 block text-sm sm:w-1/2">
        <span className="text-muted">Largest acceptable drop (optional)</span>
        <input
          name="margin"
          type="number"
          min="0"
          step="any"
          placeholder="e.g. 0.02"
          className="mt-1 block w-full rounded-md border border-line bg-background px-2 py-1.5"
        />
        <span className="mt-1 block text-xs text-muted">
          With a margin you get a pass, fail or needs more evidence decision.
        </span>
      </label>
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
