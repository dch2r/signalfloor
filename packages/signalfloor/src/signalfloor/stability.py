"""Find flaky test cases and measure the noise floor of an eval suite.

Run the same eval several times with nothing changed. A case is flaky when its score moves
between those runs by more than a tolerance. Flaky cases add noise to every comparison, so
they are worth fixing or removing.

The noise floor is how much the suite's mean score moves between two identical runs. It is
estimated two ways, and the larger is used:

- From the cases. Take two runs of n cases where case i has run-to-run variance s_i^2. If
  cases vary independently, the difference between the two run means has standard deviation
  sqrt(2 * mean(s_i^2) / n). This is precise, but it misses anything that moves many cases
  together, such as a model update, a judge change or an infrastructure problem.
- From the runs. The standard deviation of the run means, times sqrt(2) for a difference of
  two runs. This catches shared movement, but with few runs it is a rough estimate, so its
  band uses a Student t multiplier that widens when there are few runs.

A change inside the noise band is indistinguishable from rerunning the same thing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import NormalDist

import numpy as np

from signalfloor._pairing import examples, shared_case_ids
from signalfloor._tdist import t_quantile

# Below this many runs the run level estimate is rough, and the CLI says so.
FEW_RUNS = 5


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
    # The two estimates behind noise_floor. See the module docstring.
    noise_floor_cases: float
    noise_floor_runs: float
    noise_band_cases: float
    noise_band_runs: float
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
    given confidence: the larger of the band from the case estimate and the band from the
    run estimate. Flaky cases are sorted with the largest spread first.
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
    run_means = scores.mean(axis=0)
    floor_cases = float(np.sqrt(2 * per_case_variance.mean() / len(ids)))
    floor_runs = float(np.sqrt(2) * run_means.std(ddof=1))
    p = 1 - (1 - confidence) / 2
    band_cases = NormalDist().inv_cdf(p) * floor_cases
    band_runs = t_quantile(p, len(runs) - 1) * floor_runs

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
        run_means=tuple(float(m) for m in run_means),
        noise_floor=max(floor_cases, floor_runs),
        noise_band=max(band_cases, band_runs),
        noise_floor_cases=floor_cases,
        noise_floor_runs=floor_runs,
        noise_band_cases=band_cases,
        noise_band_runs=band_runs,
        confidence=confidence,
        tolerance=tolerance,
        flaky_rate=len(flaky) / len(ids),
        flaky=flaky,
    )


__all__ = ["FEW_RUNS", "FlakyCase", "Stability", "find_flaky"]
