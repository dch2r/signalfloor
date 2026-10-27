"""Compare two eval runs and decide if the difference between them is real.

Scores are assumed to be "higher is better". Each run maps a test case ID to that case's
score, and the two runs are paired by ID so a case is only ever compared with itself.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from signalfloor._pairing import PairingError, examples, shared_case_ids
from signalfloor._resample import resample_chunks


class Verdict(StrEnum):
    REGRESSION = "regression"
    IMPROVEMENT = "improvement"
    NO_CHANGE = "no_change"


@dataclass(frozen=True)
class Comparison:
    baseline_mean: float
    candidate_mean: float
    delta: float
    ci_low: float
    ci_high: float
    confidence: float
    n_cases: int
    n_resamples: int
    verdict: Verdict


def paired_bootstrap(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int | None = None,
) -> Comparison:
    """Estimate the change in mean score from baseline to candidate, with a confidence interval.

    For every case we take the difference candidate minus baseline. We then resample those
    differences with replacement many times and look at the spread of their means. If the
    whole interval sits below zero the candidate is worse, if it sits above zero it is
    better, and if it contains zero we cannot tell the change apart from noise.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence}")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be positive, got {n_resamples}")

    base, cand = _paired_arrays(baseline, candidate)
    diffs = cand - base
    n = diffs.size

    rng = np.random.default_rng(seed)
    resampled_means = _bootstrap_means(diffs, n_resamples, rng)

    alpha = 1 - confidence
    ci_low, ci_high = np.quantile(resampled_means, [alpha / 2, 1 - alpha / 2])

    if ci_high < 0:
        verdict = Verdict.REGRESSION
    elif ci_low > 0:
        verdict = Verdict.IMPROVEMENT
    else:
        verdict = Verdict.NO_CHANGE

    return Comparison(
        baseline_mean=float(base.mean()),
        candidate_mean=float(cand.mean()),
        delta=float(diffs.mean()),
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        confidence=confidence,
        n_cases=n,
        n_resamples=n_resamples,
        verdict=verdict,
    )


def _paired_arrays(
    baseline: Mapping[str, float], candidate: Mapping[str, float]
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    ids = shared_case_ids(baseline, candidate, names=("baseline", "candidate"))
    base = np.array([baseline[i] for i in ids], dtype=np.float64)
    cand = np.array([candidate[i] for i in ids], dtype=np.float64)

    for name, arr in (("baseline", base), ("candidate", cand)):
        bad = [ids[i] for i in np.flatnonzero(~np.isfinite(arr))]
        if bad:
            raise ValueError(f"{name} has non-finite scores for cases {examples(bad)}")
    return base, cand


def _bootstrap_means(
    diffs: npt.NDArray[np.float64], n_resamples: int, rng: np.random.Generator
) -> npt.NDArray[np.float64]:
    means = np.empty(n_resamples, dtype=np.float64)
    for where, idx in resample_chunks(diffs.size, n_resamples, rng):
        means[where] = diffs[idx].mean(axis=1)
    return means


__all__ = ["Comparison", "PairingError", "Verdict", "paired_bootstrap"]
