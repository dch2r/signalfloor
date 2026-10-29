"""Compare two eval runs and decide if the difference between them is real.

Scores are assumed to be "higher is better". Each run maps a test case ID to that case's
score, and the two runs are paired by ID so a case is only ever compared with itself.

Two answers come out, kept apart on purpose:

- The verdict is what the data shows: a regression, an improvement, or inconclusive.
  Inconclusive means the bounds contain zero. It does not mean nothing changed. A small eval
  can be inconclusive about a large drop.
- The decision is a release policy, and only exists when you give a margin: the largest drop
  you will accept. It passes only when the data shows any drop is smaller than that.

Both come from bounds, not straight from the bootstrap interval. The bootstrap only knows
the differences it was given. If a change breaks a few percent of all cases, a small eval can
easily contain none of them, every difference is zero, and the interval shrinks to nothing.
Two cases that both got worse give an interval of [-1, -1] the same way. So the bounds widen
the interval for cases the eval may have missed. If a share p of all cases had changed, an
eval of n cases would show none of them with chance (1 - p) ** n. The largest p that still
happens often enough is 1 - alpha ** (1 / n), close to 3.7 / n at 95% (the rule of three).

Those unseen cases only matter where they could lie beyond what was seen. A difference the
eval already contains is in the bootstrap, which resamples it. So the lower bound moves down
by p times the gap between the lowest difference seen and the lowest possible one, and the
upper bound moves up by p times the gap at the top. When the eval saw both the worst and the
best possible difference, the bounds are the interval.

This needs to know the score range, so scores must lie in a stated range, 0 to 1 unless you
say otherwise. It is never guessed from the scores seen: a sample where every score is 100.5
says nothing about how far a score can fall.

Cases that one run has and the other lacks can also be counted, as missing cases. Each could
be anything in the score range, so they widen the bounds the same way.

The widening is a safeguard checked by simulation (see studies/validation), not an exact
coverage guarantee.
"""

from __future__ import annotations

import dataclasses
import math
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
    # The share of all cases that could have changed without one showing up in this eval.
    unseen_share: float = 0.0
    # How far one case's score can move: the width of the score range.
    max_case_drop: float = 1.0
    # Cases in one run only. Each could be anywhere in the score range.
    missing_cases: int = 0
    # The lowest and highest difference seen, candidate minus baseline.
    min_diff: float = 0.0
    max_diff: float = 0.0

    @property
    def bound_low(self) -> float:
        """The lowest change in mean the data allows, counting unseen and missing cases."""
        gap = self.min_diff + self.max_case_drop
        return self._with_missing(self.ci_low - self.unseen_share * gap, -self.max_case_drop)

    @property
    def bound_high(self) -> float:
        """The highest change in mean the data allows, counting unseen and missing cases."""
        gap = self.max_case_drop - self.max_diff
        return self._with_missing(self.ci_high + self.unseen_share * gap, self.max_case_drop)

    @property
    def largest_drop_not_ruled_out(self) -> float:
        """How large a drop the data still allows. Zero when even the lower bound is a gain."""
        return max(0.0, -self.bound_low)

    def _with_missing(self, seen: float, extreme: float) -> float:
        total = self.n_cases + self.missing_cases
        return (self.n_cases * seen + self.missing_cases * extreme) / total


def cases_needed(margin: float, *, confidence: float = 0.95, max_case_drop: float = 1.0) -> int:
    """The fewest cases that can pass a margin even when nothing changed.

    Below this, a change that broke a share margin / max_case_drop of all cases would too
    often leave no trace in the eval. Raises ValueError for a margin of zero, which no number
    of cases can pass.
    """
    if not margin > 0:
        raise ValueError("no number of cases rules out every drop, so a margin of 0 never passes")
    if margin >= max_case_drop:
        return 1
    alpha = (1 - confidence) / 2
    # log1p keeps tiny margins from rounding 1 - margin to exactly 1.
    return math.ceil(math.log(alpha) / math.log1p(-margin / max_case_drop))


def paired_bootstrap(
    baseline: Mapping[str, float],
    candidate: Mapping[str, float],
    *,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int | None = None,
    margin: float | None = None,
    score_range: tuple[float, float] = (0.0, 1.0),
    missing_cases: int = 0,
) -> Comparison:
    """Estimate the change in mean score from baseline to candidate, with a confidence interval.

    For every case we take the difference candidate minus baseline. We then resample those
    differences with replacement many times and look at the spread of their means. If the
    whole interval sits below zero the candidate is worse, if it sits above zero it is
    better, and if it contains zero the data can't tell.

    The verdict and decision use the bounds, the interval widened for cases the eval may
    have missed (see the module docstring). With a margin m, the decision is fail when the
    upper bound is below -m, pass when the lower bound is at or above -m, and needs more
    evidence otherwise. Passing needs enough cases as well as a narrow interval: see
    cases_needed. A margin of zero passes only an improvement large enough to outweigh the
    cases the eval may have missed. Pick the largest drop you can live with.

    Every score must lie in score_range. missing_cases counts cases of the suite that only
    one of the runs has.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence}")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be positive, got {n_resamples}")
    if margin is not None and not (margin >= 0 and np.isfinite(margin)):
        raise ValueError(f"margin must be zero or more, got {margin}")
    lowest, highest = score_range
    if not (np.isfinite(lowest) and np.isfinite(highest) and lowest < highest):
        raise ValueError(
            f"score range must be two finite numbers, low then high, got {score_range}"
        )
    if missing_cases < 0:
        raise ValueError(f"missing_cases must be zero or more, got {missing_cases}")

    base, cand = _paired_arrays(baseline, candidate)
    for name, run in (("baseline", baseline), ("candidate", candidate)):
        outside = [i for i, score in run.items() if not lowest <= score <= highest]
        if outside:
            raise ValueError(
                f"{name} has scores outside the score range {lowest:g} to {highest:g}, for cases "
                f"{examples(sorted(outside))}. Set the score range your metric can take."
            )
    diffs = cand - base
    n = diffs.size

    rng = np.random.default_rng(seed)
    resampled_means = _bootstrap_means(diffs, n_resamples, rng)

    alpha = 1 - confidence
    ci_low, ci_high = np.quantile(resampled_means, [alpha / 2, 1 - alpha / 2])

    result = Comparison(
        baseline_mean=float(base.mean()),
        candidate_mean=float(cand.mean()),
        delta=float(diffs.mean()),
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        confidence=confidence,
        n_cases=n,
        n_resamples=n_resamples,
        verdict=Verdict.INCONCLUSIVE,
        margin=margin,
        unseen_share=1 - (alpha / 2) ** (1 / n),
        max_case_drop=highest - lowest,
        missing_cases=missing_cases,
        min_diff=float(diffs.min()),
        max_diff=float(diffs.max()),
    )
    low, high = result.bound_low, result.bound_high
    if high < 0:
        verdict = Verdict.REGRESSION
    elif low > 0:
        verdict = Verdict.IMPROVEMENT
    else:
        verdict = Verdict.INCONCLUSIVE

    decision = None
    if margin is not None:
        if high < -margin:
            decision = Decision.FAIL
        elif low >= -margin:
            decision = Decision.PASS
        else:
            decision = Decision.NEEDS_MORE_EVIDENCE
    return dataclasses.replace(result, verdict=verdict, decision=decision)


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


__all__ = ["Comparison", "Decision", "PairingError", "Verdict", "cases_needed", "paired_bootstrap"]
