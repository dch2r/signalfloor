"""Plant known regressions into real agent results and see which rule catches them.

    uv run python studies/validation/run.py

The cases are the 100 HotpotQA questions from the three v1 runs in packages/agent/results.
Each trial picks two different runs, one as baseline and one as candidate, so the real
run-to-run noise is in every comparison. It then breaks some of the candidate's correct
answers (sets their F1 to 0), which is what a change that breaks a subset of questions looks
like. The planted drop is known exactly, so every verdict can be scored as right or wrong.

An eval of n cases is drawn from the 100 questions with replacement, treating them as the
population a real eval set is sampled from. That lets n go above 100, but those rows reuse
the same 100 questions and say less than the smaller ones.

Three rules see the same data:

- naive: fail when the mean dropped by more than a threshold. This is what most eval
  dashboards and CI checks do.
- verdict: signalfloor's regression verdict, the whole 95% interval below zero.
- margin: signalfloor's release decision with the same 0.02 as the naive threshold. It passes
  only when the data rules out a drop larger than 0.02.

The table also shows the pass rule signalfloor had before this study, which looked only at
the interval. It can be worked out from each trial's ci_low, so no second run is needed.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path

import numpy as np

from signalfloor.compare import Decision, Verdict, paired_bootstrap

ROOT = Path(__file__).resolve().parents[2]
RUNS = [ROOT / "packages/agent/results" / f"v1-run{i}.jsonl" for i in (1, 2, 3)]
# Every trial, about 1 MB, so it is not committed. The summary table is.
OUT = Path(__file__).resolve().parent / "results.csv"
SUMMARY = OUT.with_name("summary.md")

PLANTED_DROPS = (0.0, 0.01, 0.02, 0.03, 0.05, 0.08)
EVAL_SIZES = (20, 50, 100, 200)
NAIVE_THRESHOLDS = (0.01, 0.02, 0.05)
MARGIN = 0.02


def load(path: Path) -> dict[str, float]:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return {row["id"]: float(row["score"]) for row in rows}


def plant(scores: np.ndarray, target: float, rng: np.random.Generator) -> np.ndarray:
    """Zero out random correct answers until the mean has dropped by at least target."""
    broken = scores.copy()
    for i in rng.permutation(np.flatnonzero(scores > 0)):
        if scores.mean() - broken.mean() >= target - 1e-12:
            break
        broken[i] = 0.0
    return broken


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    runs = [load(path) for path in RUNS]
    ids = sorted(runs[0])
    assert all(sorted(run) == ids for run in runs), "the runs must cover the same questions"
    scores = np.array([[run[i] for i in ids] for run in runs])

    rng = np.random.default_rng(args.seed)
    started = time.perf_counter()
    with OUT.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "planted_drop",
                "true_drop",
                "n",
                "observed_drop",
                "ci_low",
                "ci_high",
                "verdict",
                "decision",
            ]
        )
        for target in PLANTED_DROPS:
            for n in EVAL_SIZES:
                for _ in range(args.trials):
                    b, c = rng.choice(3, size=2, replace=False)
                    candidate = plant(scores[c], target, rng)
                    sample = rng.integers(0, len(ids), size=n)
                    # The same question can be drawn twice, so each draw gets its own key.
                    baseline = {f"{k}": scores[b][i] for k, i in enumerate(sample)}
                    cand = {f"{k}": candidate[i] for k, i in enumerate(sample)}
                    result = paired_bootstrap(
                        baseline, cand, margin=MARGIN, seed=int(rng.integers(2**32))
                    )
                    writer.writerow(
                        [
                            target,
                            round(float(scores[c].mean() - candidate.mean()), 4),
                            n,
                            round(-result.delta, 4),
                            result.ci_low,
                            result.ci_high,
                            result.verdict,
                            result.decision,
                        ]
                    )
    table = summarize(OUT)
    SUMMARY.write_text(table)
    print(f"wrote {SUMMARY.relative_to(ROOT)} in {time.perf_counter() - started:.0f}s\n")
    print(table)


def summarize(path: Path) -> str:
    """One markdown row per planted drop and eval size, each cell the share of trials."""
    with path.open(newline="") as f:
        rows = list(csv.DictReader(f))
    naive_head = " | ".join(f"naive > {t}" for t in NAIVE_THRESHOLDS)
    lines = [
        f"| planted drop | n | {naive_head} | verdict regression | interval-only pass | "
        "pass | fail | needs more evidence |",
        "|" + " ---: |" * (len(NAIVE_THRESHOLDS) + 7),
    ]
    for target in PLANTED_DROPS:
        for n in EVAL_SIZES:
            cell = [r for r in rows if float(r["planted_drop"]) == target and int(r["n"]) == n]
            drops = np.array([float(r["observed_drop"]) for r in cell])
            ci_low = np.array([float(r["ci_low"]) for r in cell])
            decisions = [r["decision"] for r in cell]
            # The pass rule before this study: the interval alone sits at or above -margin.
            interval_only = np.mean(
                (ci_low >= -MARGIN) & np.array([d != Decision.FAIL for d in decisions])
            )
            cells = [f"{np.mean(drops > t):.1%}" for t in NAIVE_THRESHOLDS]
            cells.append(f"{np.mean([r['verdict'] == Verdict.REGRESSION for r in cell]):.1%}")
            cells.append(f"{interval_only:.1%}")
            cells += [f"{decisions.count(d) / len(cell):.1%}" for d in Decision]
            lines.append(f"| {target} | {n} | " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
