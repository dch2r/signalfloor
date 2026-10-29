"""Compare two eval runs and decide if the difference between them is real.

Scores are assumed to be "higher is better". Each run maps a test case ID to that case's
score, and the two runs are paired by ID so a case is only ever compared with itself.

Two answers come out, kept apart on purpose:

- The verdict is what the data shows: a regression, an improvement, or inconclusive.
  Inconclusive means the interval contains zero. It does not mean nothing changed. A small
  eval can be inconclusive about a large drop.
- The decision is a release policy, and only exists when you give a margin: the largest drop
  you will accept. It passes only when the data shows any drop is smaller than that.
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
    INCONCLUSIVE = "inconclusive"


class Decision(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    NEEDS_MORE_EVIDENCE = "needs_more_evidence"


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
    margin: float | None = None
    decision: Decision | None = None

    @property
    def largest_drop_not_ruled_out(self) -> float:
        """How large a drop the data still allows. Zero when the interval sits above zero."""
        return max(0.0, -self.ci_low)


def paired_bootstrap(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int | None = None,
    margin: float | None = None,
) -> Comparison:
    """Estimate the change in mean score from baseline to candidate, with a confidence interval.

    For every case we take the difference candidate minus baseline. We then resample those
    differences with replacement many times and look at the spread of their means. If the
    whole interval sits below zero the candidate is worse, if it sits above zero it is
    better, and if it contains zero the data can't tell.

    With a margin m, the decision is pass when the whole interval sits at or above -m, fail
    when it sits below -m, and needs more evidence when it straddles -m. A margin of zero
    almost never passes noisy data, because the data rarely rules out every possible drop.
    Pick the largest drop you can live with.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence}")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be positive, got {n_resamples}")
    if margin is not None and not (margin >= 0 and np.isfinite(margin)):
        raise ValueError(f"margin must be zero or more, got {margin}")

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
        verdict = Verdict.INCONCLUSIVE

    decision = None
    if margin is not None:
        if ci_high < -margin:
            decision = Decision.FAIL
        elif ci_low >= -margin:
            decision = Decision.PASS
        else:
            decision = Decision.NEEDS_MORE_EVIDENCE

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
        margin=margin,
        decision=decision,
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


__all__ = ["Comparison", "Decision", "PairingError", "Verdict", "paired_bootstrap"]
