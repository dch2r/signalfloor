import type { Comparison } from "@/lib/api";
import { formatDelta, formatScore } from "@/lib/format";
import { axisExtent, toPercent } from "@/lib/interval";

const VERDICTS: Record<string, { title: string; text: string; tone: string }> = {
  regression: {
    title: "Real regression",
    text: "The candidate is worse, and the drop is larger than the noise between runs.",
    tone: "border-bad/50 bg-bad/10",
  },
  improvement: {
    title: "Real improvement",
    text: "The candidate is better, and the gain is larger than the noise between runs.",
    tone: "border-good/50 bg-good/10",
  },
  no_change: {
    title: "No real change",
    text: "The difference is within the noise. It could go either way on a rerun.",
    tone: "border-line bg-subtle",
  },
};

export function VerdictBanner({ comparison }: { comparison: Comparison }) {
  const verdict = VERDICTS[comparison.verdict] ?? VERDICTS.no_change;
  const percent = Math.round(comparison.confidence * 100);

  return (
    <section className={`rounded-lg border p-5 ${verdict.tone}`}>
      <p className="text-lg font-semibold">{verdict.title}</p>
      <p className="mt-1 text-sm text-muted">{verdict.text}</p>

      <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <Stat label="Baseline mean" value={formatScore(comparison.baseline_mean)} />
        <Stat label="Candidate mean" value={formatScore(comparison.candidate_mean)} />
        <Stat label="Change" value={formatDelta(comparison.delta)} />
        <Stat
          label={`${percent}% interval`}
          value={`${formatDelta(comparison.ci_low)} to ${formatDelta(comparison.ci_high)}`}
        />
      </dl>

      <IntervalAxis comparison={comparison} />

      <p className="mt-3 text-xs text-muted">
        Paired bootstrap over {comparison.n_cases} shared cases with{" "}
        {comparison.n_resamples.toLocaleString("en-US")} resamples.
      </p>
    </section>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted">{label}</dt>
      <dd className="font-mono text-base tabular-nums">{value}</dd>
    </div>
  );
}

/** The interval on an axis centred on zero. If the bar crosses the zero line, it is noise. */
export function IntervalAxis({ comparison }: { comparison: Comparison }) {
  const { ci_low, ci_high, delta } = comparison;
  const extent = axisExtent([ci_low, ci_high, delta]);
  const left = toPercent(ci_low, extent);
  const right = toPercent(ci_high, extent);

  return (
    <div
      className="relative mt-5 h-8"
      role="img"
      aria-label={`Interval from ${formatDelta(ci_low)} to ${formatDelta(ci_high)}, zero marked`}
    >
      <div className="absolute inset-x-0 top-1/2 h-px bg-line" />
      <div className="absolute top-0 h-full w-px bg-muted" style={{ left: "50%" }} />
      <div
        data-testid="interval"
        className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-foreground/60"
        style={{ left: `${left}%`, width: `${Math.max(right - left, 0.5)}%` }}
      />
      <div
        className="absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground"
        style={{ left: `${toPercent(delta, extent)}%` }}
      />
      <span className="absolute -bottom-4 -translate-x-1/2 text-xs text-muted" style={{ left: "50%" }}>
        0
      </span>
    </div>
  );
}
