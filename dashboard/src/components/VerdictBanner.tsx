import type { Comparison } from "@/lib/api";
import { formatCount, formatDelta, formatScore } from "@/lib/format";
import { axisExtent, toPercent } from "@/lib/interval";

// The interval comes from resampling the eval's cases. It shows how much the result depends on
// which cases happen to be in the eval set. It is not a measure of run to run noise. The bounds
// are a confidence interval by betting, which holds at any sample size, and the verdict and
// decision come from them. Statistical evidence, not certainty, so the wording never says
// proven.
const VERDICTS: Record<string, { title: string; text: string; tone: string }> = {
  regression: {
    title: "Regression",
    text: "The candidate is likely worse. The bounds, which hold even for small evals, sit below zero.",
    tone: "border-bad/50 bg-bad/10",
  },
  improvement: {
    title: "Improvement",
    text: "The candidate is likely better. The bounds, which hold even for small evals, sit above zero.",
    tone: "border-good/50 bg-good/10",
  },
  inconclusive: {
    title: "Inconclusive",
    text: "The bounds include zero, so the data can't tell which way this went. That is not the same as no change.",
    tone: "border-line bg-subtle",
  },
};

const DECISIONS: Record<string, { label: string; tone: string; text: (margin: string) => string }> = {
  pass: {
    label: "Pass",
    tone: "bg-good/15 text-good",
    text: (m) => `The bounds rule out a drop larger than ${m}.`,
  },
  fail: {
    label: "Fail",
    tone: "bg-bad/15 text-bad",
    text: (m) => `The bounds put the drop above ${m}.`,
  },
  needs_more_evidence: {
    label: "Needs more evidence",
    tone: "bg-foreground/10",
    text: (m) => `The data can't tell if the drop is within ${m}. More cases would narrow the interval.`,
  },
};

export function VerdictBanner({ comparison }: { comparison: Comparison }) {
  const verdict = VERDICTS[comparison.verdict] ?? VERDICTS.inconclusive;
  const decision = comparison.decision ? DECISIONS[comparison.decision] : undefined;
  const percent = Math.round(comparison.confidence * 100);
  const margin = formatScore(comparison.margin ?? 0);

  return (
    <section className={`rounded-lg border p-5 ${verdict.tone}`}>
      <div className="flex flex-wrap items-center gap-3">
        <p className="text-lg font-semibold">{verdict.title}</p>
        {decision && (
          <span
            data-testid="decision"
            className={`rounded-full px-2.5 py-0.5 text-sm font-medium ${decision.tone}`}
          >
            {decision.label}
          </span>
        )}
      </div>
      <p className="mt-1 text-sm text-muted">{verdict.text}</p>
      {comparison.verdict === "inconclusive" && (
        <p className="mt-1 text-sm">
          A drop of up to{" "}
          <strong className="font-mono">{formatScore(comparison.largest_drop_not_ruled_out)}</strong>{" "}
          can&apos;t be ruled out.
        </p>
      )}
      {decision && <p className="mt-1 text-sm">{decision.text(margin)}</p>}
      {comparison.missing_cases > 0 && (
        <p data-testid="missing-cases" className="mt-1 text-sm">
          {formatCount(comparison.missing_cases)}{" "}
          {comparison.missing_cases === 1 ? "case is" : "cases are"} in only one run. Each counts
          as anything from the lowest to the highest score, which widens the bounds.
        </p>
      )}
      {comparison.decision === "needs_more_evidence" &&
        comparison.cases_needed != null &&
        comparison.n_cases < comparison.cases_needed && (
          <p data-testid="cases-needed" className="mt-1 text-sm">
            When nothing changes, a margin of {margin} needs at least{" "}
            <strong className="font-mono">{comparison.cases_needed}</strong> cases. With{" "}
            {comparison.n_cases}, even an unchanged eval can&apos;t rule out a drop of{" "}
            {formatScore(comparison.no_change_drop)}.
          </p>
        )}

      <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-4">
        <Stat label="Baseline mean" value={formatScore(comparison.baseline_mean)} />
        <Stat label="Candidate mean" value={formatScore(comparison.candidate_mean)} />
        <Stat label="Change" value={formatDelta(comparison.delta)} />
        <Stat
          label={`${percent}% bootstrap interval`}
          value={`${formatDelta(comparison.ci_low)} to ${formatDelta(comparison.ci_high)}`}
        />
      </dl>
      <p className="mt-2 text-sm text-muted">
        {percent}% bounds, which the verdict uses and which hold at any sample size:{" "}
        <span data-testid="bounds" className="font-mono">
          {formatDelta(comparison.bound_low)} to {formatDelta(comparison.bound_high)}
        </span>
      </p>

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
