"""Compare two eval runs and decide if the difference between them is real.

Scores are assumed to be "higher is better". Each run maps a test case ID to that case's
score, and the two runs are paired by ID so a case is only ever compared with itself.

Two answers come out, kept apart on purpose:

- The verdict is what the data shows: a regression, an improvement, or inconclusive.
  Inconclusive means the bounds contain zero. It does not mean nothing changed. A small eval
  can be inconclusive about a large drop.
- The decision is a release policy, and only exists when you give a margin: the largest drop
  you will accept. It passes only when the data shows any drop is smaller than that.

Both come from bounds, not from the bootstrap interval. A percentile bootstrap only reaches
its stated coverage as samples grow. On small or lopsided samples it can be badly wrong: two
cases that both got worse give an interval of [-1, -1], and an eval that happens to contain
none of the cases a change broke gives [0, 0]. The bounds are a confidence interval by
betting (see _betting.py), which holds at every sample size for independently drawn cases
with scores in a known range. The bootstrap interval is still reported, as a quick
description of the data, but no call is made from it.

That needs the score range, so scores must lie in a stated range, 0 to 1 unless you say
otherwise. It is never guessed from the scores seen: a sample where every score is 100.5
says nothing about how far a score can fall.

Cases that one run has and the other lacks can also be counted, as missing cases. Each could
be anything in the score range, so they widen the bounds by their share of the suite.
"""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

import numpy as np
import numpy.typing as npt

from signalfloor._betting import betting_interval, no_change_half_width
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
    # The confidence interval by betting, widened for missing cases. Calls come from these.
    bound_low: float = 0.0
    bound_high: float = 0.0
    # How far one case's score can move: the width of the score range.
    max_case_drop: float = 1.0
    # Cases in one run only. Each could be anywhere in the score range.
    missing_cases: int = 0

    @property
    def largest_drop_not_ruled_out(self) -> float:
        """How large a drop the data still allows. Zero when even the lower bound is a gain."""
        return max(0.0, -self.bound_low)

    @property
    def no_change_drop(self) -> float:
        """The drop this many cases can't rule out even when every difference is zero."""
        return no_change_drop(self.n_cases, self.confidence, self.max_case_drop)


@functools.lru_cache(maxsize=4096)
def no_change_drop(n: int, confidence: float = 0.95, max_case_drop: float = 1.0) -> float:
    """The drop an eval of n cases can't rule out even when nothing changed at all."""
    return 2 * max_case_drop * no_change_half_width(n, 1 - confidence)


# Past this, cases_needed stops searching. The search costs time proportional to the count.
MAX_CASES_SEARCHED = 1_000_000


@functools.lru_cache(maxsize=1024)
def cases_needed(
    margin: float, *, confidence: float = 0.95, max_case_drop: float = 1.0
) -> int | None:
    """The fewest cases that pass a margin when nothing changed, or None past a million.

    This is the count for the case where every difference is exactly zero. An eval with a
    clear improvement can pass with fewer, and one with any losses needs more. Raises
    ValueError for a margin of zero, which an unchanged eval never passes.
    """
    if not margin > 0:
        raise ValueError("an unchanged eval can't rule out every drop, so it never passes 0")
    if no_change_drop(1, confidence, max_case_drop) <= margin:
        return 1
    low, high = 1, 2
    while no_change_drop(high, confidence, max_case_drop) > margin:
        if high >= MAX_CASES_SEARCHED:
            return None
        low, high = high, min(high * 2, MAX_CASES_SEARCHED)
    while high - low > 1:
        middle = (low + high) // 2
        if no_change_drop(middle, confidence, max_case_drop) > margin:
            low = middle
        else:
            high = middle
    return high


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

    The verdict and decision use the bounds, a confidence interval by betting (see the module
    docstring). With a margin m, the decision is fail when the upper bound is below -m, pass
    when the lower bound is at or above -m, and needs more evidence otherwise. Passing needs
    enough cases as well as a clear result: see cases_needed. Pick the largest drop you can
    live with.

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

    # Differences lie between -width and +width. The betting interval needs [0, 1].
    width = highest - lowest
    seen_low, seen_high = betting_interval((diffs + width) / (2 * width), alpha)
    total = n + missing_cases
    low = (n * (2 * width * seen_low - width) - missing_cases * width) / total
    high = (n * (2 * width * seen_high - width) + missing_cases * width) / total
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
        bound_low=low,
        bound_high=high,
        max_case_drop=width,
        missing_cases=missing_cases,
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


__all__ = [
    "Comparison",
    "Decision",
    "PairingError",
    "Verdict",
    "cases_needed",
    "no_change_drop",
    "paired_bootstrap",
]
