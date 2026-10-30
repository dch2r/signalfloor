"""Confidence intervals for a bounded mean by betting.

From Waudby-Smith and Ramdas, "Estimating means of bounded random variables by betting"
(JRSS-B, 2024). The interval is valid at every sample size, with no approximation, for
independent draws from any distribution on [0, 1]. A percentile bootstrap only approaches
its stated coverage as the sample grows, and on small or lopsided samples it can be far off.

The idea: for each candidate mean m, a gambler bets that the data will come out above m and
another bets it will come out below. A bet that wins a lot of money is evidence against m.
If m is the true mean, neither bet can be expected to make money, so by Markov's inequality
their combined wealth reaches 1/alpha with chance at most alpha. The interval is every m
where the wealth stays below 1/alpha.

The wealth depends on the order the data is bet on. Averaging it over several orderings
keeps the result steady and stays valid, because the average of values whose expectation is
at most 1 also has expectation at most 1. The orderings come from a fixed seed applied to
the order the cases were given in, so the same data always gives the same interval.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import numpy as np
import numpy.typing as npt

# How many orderings to average over, and how much of the wealth one bet may risk.
ORDERINGS = 20
_RISK = 0.75
_SEED = 0
_EDGE = 1e-9


def betting_interval(x: npt.NDArray[np.float64], alpha: float) -> tuple[float, float]:
    """A 1 - alpha confidence interval for the mean of x, which must lie in [0, 1]."""
    data, bets = _prepare(x, alpha)
    threshold = math.log(1 / alpha)

    def rejected(m: float) -> bool:
        return _log_wealth(data, bets, m) >= threshold

    center = float(x.mean())
    if rejected(center):
        # Not seen in testing, but if the mean itself were rejected the interval would be
        # empty. Report the mean alone rather than invent a range.
        return center, center
    return _edge(rejected, center, 0.0), _edge(rejected, center, 1.0)


def rejects(x: npt.NDArray[np.float64], m: float, alpha: float) -> bool:
    """Whether the 1 - alpha interval for the mean of x leaves out m. One check, no search."""
    data, bets = _prepare(x, alpha)
    return _log_wealth(data, bets, m) >= math.log(1 / alpha)


def _prepare(
    x: npt.NDArray[np.float64], alpha: float
) -> tuple[npt.NDArray[np.float64], npt.NDArray[np.float64]]:
    """The data in each ordering, and the bet for each step of each ordering."""
    rng = np.random.default_rng(_SEED)
    data = np.stack([x[rng.permutation(x.size)] for _ in range(ORDERINGS)])
    return data, _bet_sizes(data, alpha)


def _bet_sizes(data: npt.NDArray[np.float64], alpha: float) -> npt.NDArray[np.float64]:
    """The predictable plug-in bet for each step: larger when past data has varied less."""
    n = data.shape[1]
    steps = np.arange(1, n + 1)
    mean = (0.5 + np.cumsum(data, axis=1)) / (steps + 1)
    before = np.concatenate([np.full((data.shape[0], 1), 0.5), mean[:, :-1]], axis=1)
    variance = (0.25 + np.cumsum((data - before) ** 2, axis=1)) / (steps + 1)
    previous = np.concatenate([np.full((data.shape[0], 1), 0.25), variance[:, :-1]], axis=1)
    bets: npt.NDArray[np.float64] = np.sqrt(2 * math.log(2 / alpha) / (n * previous))
    return bets


def _log_wealth(data: npt.NDArray[np.float64], bets: npt.NDArray[np.float64], m: float) -> float:
    """log of the two bets' combined wealth against mean m, averaged over the orderings.

    At m of exactly 0 or 1 the bet size limit divides by zero, so m is moved in by a hair for
    the arithmetic. The interval's ends are still reported exactly (see _edge).
    """
    m = min(max(m, _EDGE), 1 - _EDGE)
    gap = data - m
    up = np.log1p(np.minimum(bets, _RISK / m) * gap).sum(axis=1)
    down = np.log1p(-np.minimum(bets, _RISK / (1 - m)) * gap).sum(axis=1)
    per_order = np.logaddexp(up, down) + math.log(0.5)
    # log of the mean wealth, computed without overflow.
    top = float(np.max(per_order))
    return top + math.log(float(np.mean(np.exp(per_order - top))))


def _edge(rejected: Callable[[float], bool], inside: float, outside: float) -> float:
    """Bisect for where the interval ends between a kept point and a far end.

    A far end that can't be rejected is part of the interval, and is returned exactly: data
    that is all 0 must keep 0. Otherwise the result is the rejected side of the last step, so
    rounding only ever widens the interval.
    """
    if not rejected(outside):
        return outside
    for _ in range(50):
        mid = (inside + outside) / 2
        if rejected(mid):
            outside = mid
        else:
            inside = mid
    return outside


def no_change_half_width(n: int, alpha: float) -> float:
    """How far the interval reaches either side for n values that are all exactly 0.5.

    That is n cases where nothing changed. Every ordering is the same, so one is enough.
    """
    data = np.full((1, n), 0.5)
    bets = _bet_sizes(data, alpha)
    threshold = math.log(1 / alpha)
    low = _edge(lambda m: _log_wealth(data, bets, m) >= threshold, 0.5, 0.0)
    return 0.5 - low
