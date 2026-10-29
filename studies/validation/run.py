"""Plant known regressions into real agent results and score each release rule.

    uv run python studies/validation/run.py --data dev
    uv run python studies/validation/run.py --data fresh

Two sets of real results, both from the reference agent's v1 prompt on HotpotQA:

- dev: the first 100 questions, three runs. The safeguards in signalfloor were shaped on
  these, so results here are development evidence.
- fresh: the next 100 questions, run after those safeguards were written. Nothing was tuned
  on them, so they are the check.

Each trial picks a baseline run and a candidate run (different runs when there are several,
so real run-to-run noise is included), damages the candidate in a known way, draws an eval of
n cases with replacement, and asks every rule for a release call at margins 0.02 and 0.05.
A margin of 0.02 needs 183 cases to ever pass and 0.05 needs 72, so the two show the rules
below and above that size. Each comparison uses 2,000 resamples to keep the run short. Three
kinds of damage:

- break: random correct answers drop to F1 0. A change that breaks a subset.
- partial: every answer loses the same share of its credit. A change that hurts a little
  everywhere.
- churn: 5% of wrong answers become right, and enough right answers break to reach the
  planted drop. Many cases move both ways, which is where false failures come from.

Four rules see the same trials:

- naive: fail when the mean dropped by more than the margin. What most eval checks do.
- interval-only: pass when the bootstrap interval sits at or above -margin, fail when it sits
  below. signalfloor's first margin rule.
- 0.3.0: interval-only, but passing also allows for cases the eval may have missed.
- bounds: the current rule. Both ends widened past the most extreme differences seen.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from signalfloor.compare import Decision, paired_bootstrap

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DATA = {
    "dev": [ROOT / "packages/agent/results" / f"v1-run{i}.jsonl" for i in (1, 2, 3)],
    "fresh": sorted((ROOT / "packages/agent/results").glob("fresh-v1-run*.jsonl")),
}

PATTERNS = ("break", "partial", "churn")
PLANTED_DROPS = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08)
EVAL_SIZES = (20, 50, 100, 200)
MARGINS = (0.02, 0.05)
RULES = ("naive", "interval-only", "0.3.0", "bounds")


def classes(margin: float) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """Planted drops you would ship (at most half the margin) and ones you wouldn't (above it).

    Drops in between are run but not scored.
    """
    acceptable = tuple(d for d in PLANTED_DROPS if d <= margin / 2)
    return acceptable, tuple(d for d in PLANTED_DROPS if d > margin)


def load(path: Path) -> dict[str, float]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {row["id"]: float(row["score"]) for row in rows}


def damage(scores: np.ndarray, pattern: str, target: float, rng: np.random.Generator) -> np.ndarray:
    """The candidate's scores after a change that lowers the mean by about target."""
    if pattern == "partial":
        return scores * (1 - target / scores.mean())
    changed = scores.copy()
    if pattern == "churn":
        wrong = np.flatnonzero(scores == 0)
        changed[rng.choice(wrong, size=round(0.05 * scores.size), replace=False)] = 1.0
    for i in rng.permutation(np.flatnonzero(scores > 0)):
        if scores.mean() - changed.mean() >= target - 1e-12:
            break
        changed[i] = 0.0
    return changed


def decide(rule: str, row: dict[str, str], margin: float) -> str:
    """The release call each rule makes from one trial's numbers."""
    if rule == "naive":
        return Decision.FAIL if float(row["observed_drop"]) > margin else Decision.PASS
    if rule == "bounds":
        low, high = float(row["bound_low"]), float(row["bound_high"])
    else:
        low, high = float(row["ci_low"]), float(row["ci_high"])
    if high < -margin:
        return Decision.FAIL
    if rule == "0.3.0":
        p = float(row["unseen_share"])
        low = (1 - p) * low - p
    return Decision.PASS if low >= -margin else Decision.NEEDS_MORE_EVIDENCE


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", choices=sorted(DATA), default="dev")
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    paths = DATA[args.data]
    if not paths:
        parser.error(f"no result files for {args.data}")
    runs = [load(path) for path in paths]
    ids = sorted(runs[0])
    assert all(sorted(run) == ids for run in runs), "the runs must cover the same questions"
    scores = np.array([[run[i] for i in ids] for run in runs])

    out = HERE / f"results-{args.data}.csv"
    rng = np.random.default_rng(args.seed)
    started = time.perf_counter()
    with out.open("w", newline="") as f:
        writer = csv.writer(f)
        columns = "pattern planted_drop n observed_drop ci_low ci_high unseen_share"
        columns += " bound_low bound_high"
        writer.writerow(columns.split())
        for pattern in PATTERNS:
            for target in PLANTED_DROPS:
                for n in EVAL_SIZES:
                    for _ in range(args.trials):
                        if len(runs) > 1:
                            b, c = rng.choice(len(runs), size=2, replace=False)
                        else:
                            b = c = 0
                        candidate = damage(scores[c], pattern, target, rng)
                        sample = rng.integers(0, len(ids), size=n)
                        # The same question can be drawn twice, so each draw gets its own key.
                        result = paired_bootstrap(
                            {f"{k}": scores[b][i] for k, i in enumerate(sample)},
                            {f"{k}": candidate[i] for k, i in enumerate(sample)},
                            n_resamples=2_000,
                            seed=int(rng.integers(2**32)),
                        )
                        numbers = (result.ci_low, result.ci_high, result.unseen_share)
                        bounds = (result.bound_low, result.bound_high)
                        writer.writerow((pattern, target, n, -result.delta, *numbers, *bounds))
    summary = HERE / f"summary-{args.data}.md"
    summary.write_text(summarize(out, args.data, len(runs)))
    elapsed = time.perf_counter() - started
    print(f"wrote {summary.relative_to(ROOT)} in {elapsed:.0f}s\n")
    print(summary.read_text())


def rates(rows: list[dict[str, str]], rule: str, margin: float) -> dict[str, float]:
    calls = [decide(rule, r, margin) for r in rows]
    return {d: calls.count(d) / len(calls) for d in Decision}


def summarize(path: Path, data: str, n_runs: int) -> str:
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    header = f"# {data}: {len(rows):,} trials from {n_runs} run(s)\n"
    return header + "".join(summarize_margin(rows, margin) for margin in MARGINS)


def summarize_margin(rows: list[dict[str, str]], margin: float) -> str:
    acceptable, bad = classes(margin)

    def pick(drops: tuple[float, ...], n: int, pattern: str | None = None) -> list[dict[str, str]]:
        return [
            r
            for r in rows
            if float(r["planted_drop"]) in drops
            and int(r["n"]) == n
            and (pattern is None or r["pattern"] == pattern)
        ]

    lines = [
        "",
        f"## Margin {margin}",
        "",
        f"Acceptable changes are planted drops of {', '.join(map(str, acceptable))}, bad ones "
        f"{', '.join(map(str, bad))}.",
        "All three damage patterns are pooled. Each cell is the share of trials.",
        "",
        "| n | rule | acceptable: pass | acceptable: fail | acceptable: more evidence "
        "| bad: pass | bad: fail | bad: more evidence |",
        "|" + " ---: |" * 2 + " ---: |" * 6,
    ]
    for n in EVAL_SIZES:
        for rule in RULES:
            good = rates(pick(acceptable, n), rule, margin)
            worse = rates(pick(bad, n), rule, margin)
            order = (Decision.PASS, Decision.FAIL, Decision.NEEDS_MORE_EVIDENCE)
            cells = [good[d] for d in order] + [worse[d] for d in order]
            lines.append(f"| {n} | {rule} | " + " | ".join(f"{c:.1%}" for c in cells) + " |")

    lines += [
        "",
        f"### By damage pattern, margin {margin}",
        "",
        "Unsafe approvals (bad: pass) and false failures (acceptable: fail) for each pattern.",
        "",
        "| pattern | n | " + " | ".join(f"{r} unsafe pass | {r} false fail" for r in RULES) + " |",
        "|" + " ---: |" * (2 + 2 * len(RULES)),
    ]
    for pattern in PATTERNS:
        for n in EVAL_SIZES:
            cells = []
            for rule in RULES:
                good = rates(pick(acceptable, n, pattern), rule, margin)
                worse = rates(pick(bad, n, pattern), rule, margin)
                cells += [f"{worse[Decision.PASS]:.1%}", f"{good[Decision.FAIL]:.1%}"]
            lines.append(f"| {pattern} | {n} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
