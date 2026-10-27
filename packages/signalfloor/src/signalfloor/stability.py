"""Find flaky test cases and measure the noise floor of an eval suite.

Run the same eval several times with nothing changed. A case is flaky when its score moves
between those runs by more than a tolerance. Flaky cases add noise to every comparison, so
they are worth fixing or removing.

The noise floor is how much the suite's mean score moves between two identical runs. Take
two runs of n cases where case i has run-to-run variance s_i^2. The difference between the
two run means is the average of n per-case differences, each with variance 2 * s_i^2, so

    noise floor = sqrt(2 * mean(s_i^2) / n)

is the standard deviation of that difference. A change smaller than about two noise floors
is indistinguishable from rerunning the same thing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

from signalfloor._pairing import examples, shared_case_ids


@dataclass(frozen=True)
class FlakyCase:
    case_id: str
    scores: tuple[float, ...]
    mean: float
    spread: float


@dataclass(frozen=True)
class Stability:
    n_runs: int
    n_cases: int
    run_means: tuple[float, ...]
    noise_floor: float
    noise_band: float
    confidence: float
    tolerance: float
    flaky_rate: float
    flaky: tuple[FlakyCase, ...]


def find_flaky(
    runs: Sequence[Mapping[str, float]],
    *,
    tolerance: float = 0.0,
    confidence: float = 0.95,
) -> Stability:
    """Compare repeated runs of the same eval and report flaky cases and the noise floor.

    A case is flaky when the gap between its highest and lowest score across runs is
    greater than tolerance. The default of 0 flags any change, which suits pass/fail
    scores. For continuous scores pick a tolerance that matters to you, like 0.1.

    noise_band is the size of change that run-to-run noise alone stays within at the
    given confidence. Flaky cases are sorted with the largest spread first.
    """
    if len(runs) < 2:
        raise ValueError(f"need at least 2 runs to measure flakiness, got {len(runs)}")
    if tolerance < 0:
        raise ValueError(f"tolerance must not be negative, got {tolerance}")
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence}")

    ids = shared_case_ids(runs[0], runs[1], names=("run 1", "run 2"))
    for k, run in enumerate(runs[2:], start=3):
        shared_case_ids(runs[0], run, names=("run 1", f"run {k}"))

    # One row per case, one column per run.
    scores = np.array([[run[i] for run in runs] for i in ids], dtype=np.float64)
    bad = [ids[r] for r in np.flatnonzero(~np.isfinite(scores).all(axis=1))]
    if bad:
        raise ValueError(f"non-finite scores for cases {examples(bad)}")

    spreads = scores.max(axis=1) - scores.min(axis=1)
    per_case_variance = scores.var(axis=1, ddof=1)
    noise_floor = float(np.sqrt(2 * per_case_variance.mean() / len(ids)))
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)

    flaky_rows = sorted(np.flatnonzero(spreads > tolerance), key=lambda r: (-spreads[r], ids[r]))
    flaky = tuple(
        FlakyCase(
            case_id=ids[r],
            scores=tuple(float(s) for s in scores[r]),
            mean=float(scores[r].mean()),
            spread=float(spreads[r]),
        )
        for r in flaky_rows
    )

    return Stability(
        n_runs=len(runs),
        n_cases=len(ids),
        run_means=tuple(float(m) for m in scores.mean(axis=0)),
        noise_floor=noise_floor,
        noise_band=z * noise_floor,
        confidence=confidence,
        tolerance=tolerance,
        flaky_rate=len(flaky) / len(ids),
        flaky=flaky,
    )


__all__ = ["FlakyCase", "Stability", "find_flaky"]
