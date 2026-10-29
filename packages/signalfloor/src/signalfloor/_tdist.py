"""Student's t quantiles, without depending on scipy for one function."""

from __future__ import annotations

import math


def t_quantile(p: float, df: int) -> float:
    """The value t such that P(T <= t) = p for Student's t with df degrees of freedom."""
    if not 0.5 <= p < 1:
        raise ValueError(f"p must be in [0.5, 1), got {p}")
    if df < 1:
        raise ValueError(f"df must be at least 1, got {df}")
    if p == 0.5:
        return 0.0
    low, high = 0.0, 1.0
    while _cdf(high, df) < p:
        high *= 2
    # Bisection. 200 halvings is far past double precision for any interval here.
    for _ in range(200):
        mid = (low + high) / 2
        if _cdf(mid, df) < p:
            low = mid
        else:
            high = mid
    return (low + high) / 2


def _cdf(t: float, df: int) -> float:
    """P(T <= t) for t >= 0."""
    x = df / (df + t * t)
    return 1 - 0.5 * _incomplete_beta(x, df / 2, 0.5)


def _incomplete_beta(x: float, a: float, b: float) -> float:
    """The regularized incomplete beta function I_x(a, b), by its continued fraction."""
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b) + a * math.log(x) + b * math.log1p(-x)
    )
    # The continued fraction converges fast on this side. Use the symmetry otherwise.
    if x < (a + 1) / (a + b + 2):
        return front * _beta_fraction(x, a, b) / a
    return 1 - front * _beta_fraction(1 - x, b, a) / b


def _beta_fraction(x: float, a: float, b: float) -> float:
    # Modified Lentz's method.
    tiny = 1e-300
    c, d = 1.0, 1 - (a + b) * x / (a + 1)
    d = 1 / (d if abs(d) > tiny else tiny)
    result = d
    for m in range(1, 300):
        for numerator in (
            m * (b - m) * x / ((a + 2 * m - 1) * (a + 2 * m)),
            -(a + m) * (a + b + m) * x / ((a + 2 * m) * (a + 2 * m + 1)),
        ):
            d = 1 + numerator * d
            d = 1 / (d if abs(d) > tiny else tiny)
            c = 1 + numerator / c
            c = c if abs(c) > tiny else tiny
            result *= c * d
        if abs(c * d - 1) < 1e-15:
            return result
    # Converges in a few dozen steps for every input used here. A wrong number would be worse
    # than an error.
    raise ArithmeticError("incomplete beta did not converge")  # pragma: no cover
