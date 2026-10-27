"""Measure how well an LLM judge agrees with human labels.

Raw agreement is misleading when one label is common. If 90% of answers are good, a judge
that always says "good" agrees with humans 90% of the time and is still useless. Cohen's
kappa fixes this by subtracting the agreement you would expect by chance:

    kappa = 1 - observed disagreement / disagreement expected by chance

1 means perfect agreement, 0 means no better than chance, and below 0 means worse than
chance. For ordered labels like 1 to 5 ratings, weighted kappa gives partial credit when
the judge is close: a 4 against a human 5 is penalised less than a 1 against a 5.
"""

from __future__ import annotations

import numbers
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

import numpy as np
import numpy.typing as npt

from signalfloor._pairing import shared_case_ids
from signalfloor._resample import resample_chunks

Label = str | int | float | bool
Weights = Literal["linear", "quadratic"]


class Trust(StrEnum):
    TRUSTED = "trusted"
    UNTRUSTED = "untrusted"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True)
class Agreement:
    n_cases: int
    categories: tuple[Label, ...]
    raw_agreement: float
    kappa: float
    ci_low: float
    ci_high: float
    confidence: float
    threshold: float
    weights: Weights | None
    judge_bias: float | None
    n_resamples: int
    verdict: Trust


def judge_agreement(
    judge: Mapping[str, Label],
    human: Mapping[str, Label],
    *,
    weights: Weights | None = None,
    threshold: float = 0.6,
    confidence: float = 0.95,
    n_resamples: int = 10_000,
    seed: int | None = None,
) -> Agreement:
    """Compare judge labels with human labels on the same cases.

    The verdict uses the whole confidence interval for kappa, not just the point estimate.
    If even the low end of the interval clears the threshold the judge is trusted. If even
    the high end misses it the judge is untrusted. Otherwise there are not enough labelled
    cases to say, and the answer is inconclusive.

    The default threshold of 0.6 is the usual cut off for "substantial" agreement.
    judge_bias is the mean judge label minus the mean human label when labels are numbers.
    A positive value means the judge is more lenient than humans.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be between 0 and 1, got {confidence}")
    if not -1 <= threshold <= 1:
        raise ValueError(f"threshold must be between -1 and 1, got {threshold}")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be positive, got {n_resamples}")

    ids = shared_case_ids(judge, human, names=("judge", "human"))
    judge_labels = [_normalize(judge[i]) for i in ids]
    human_labels = [_normalize(human[i]) for i in ids]
    categories = _categories(judge_labels + human_labels, ordered=weights is not None)

    position = {c: k for k, c in enumerate(categories)}
    j = np.array([position[x] for x in judge_labels], dtype=np.int64)
    h = np.array([position[x] for x in human_labels], dtype=np.int64)
    disagreement = _disagreement_weights(categories, weights)

    kappa = float(_kappa(_confusion(j, h, len(categories))[np.newaxis], disagreement)[0])
    if np.isnan(kappa):
        raise ValueError(
            "kappa is undefined because judge and human gave every case the same single label"
        )

    rng = np.random.default_rng(seed)
    resampled = np.empty(n_resamples, dtype=np.float64)
    for where, idx in resample_chunks(len(ids), n_resamples, rng):
        resampled[where] = _kappa(_batch_confusion(j[idx], h[idx], len(categories)), disagreement)

    alpha = 1 - confidence
    # A resample can draw only one label and leave kappa undefined. Those carry no
    # information about agreement, so they are left out of the interval.
    ci_low, ci_high = np.nanquantile(resampled, [alpha / 2, 1 - alpha / 2])

    if ci_low >= threshold:
        verdict = Trust.TRUSTED
    elif ci_high < threshold:
        verdict = Trust.UNTRUSTED
    else:
        verdict = Trust.INCONCLUSIVE

    numeric = all(isinstance(c, int | float) for c in categories)
    bias = (
        float(
            np.mean([float(a) - float(b) for a, b in zip(judge_labels, human_labels, strict=True)])
        )
        if numeric
        else None
    )

    return Agreement(
        n_cases=len(ids),
        categories=tuple(categories),
        raw_agreement=float(np.mean(j == h)),
        kappa=kappa,
        ci_low=float(ci_low),
        ci_high=float(ci_high),
        confidence=confidence,
        threshold=threshold,
        weights=weights,
        judge_bias=bias,
        n_resamples=n_resamples,
        verdict=verdict,
    )


def _normalize(label: object) -> Label:
    # Turn numpy and other numeric types into plain int or float. This also maps true/false
    # to 1/0, so a judge returning booleans lines up with humans who labelled with numbers.
    if isinstance(label, numbers.Integral):
        return int(label)
    if isinstance(label, numbers.Real):
        return float(label)
    if isinstance(label, str):
        return label
    raise ValueError(f"labels must be numbers, booleans or strings, got {label!r}")


def _categories(labels: list[Label], *, ordered: bool) -> list[Label]:
    unique = set(labels)
    numeric = all(isinstance(x, int | float) for x in unique)
    if ordered and not numeric:
        raise ValueError("weighted kappa needs numeric labels, like 1 to 5 ratings")
    if not numeric and not all(isinstance(x, str) for x in unique):
        raise ValueError("labels must be all numbers or all strings, not a mix")
    return sorted(unique, key=lambda x: (0, x) if numeric else (1, str(x)))


def _disagreement_weights(
    categories: list[Label], weights: Weights | None
) -> npt.NDArray[np.float64]:
    k = len(categories)
    if weights is None:
        return 1.0 - np.eye(k)
    values = np.array(categories, dtype=np.float64)
    spread = float(np.max(values) - np.min(values))
    if spread == 0:
        return np.zeros((k, k))
    distance: npt.NDArray[np.float64] = np.abs(values[:, None] - values[None, :]) / spread
    return distance if weights == "linear" else distance**2


def _confusion(
    j: npt.NDArray[np.int64], h: npt.NDArray[np.int64], k: int
) -> npt.NDArray[np.float64]:
    return np.bincount(j * k + h, minlength=k * k).reshape(k, k).astype(np.float64)


def _batch_confusion(
    j: npt.NDArray[np.int64], h: npt.NDArray[np.int64], k: int
) -> npt.NDArray[np.float64]:
    """Confusion matrices for many resamples at once. j and h have shape (rows, n_cases)."""
    rows = j.shape[0]
    offsets = np.arange(rows, dtype=np.int64)[:, None] * (k * k)
    codes = (offsets + j * k + h).ravel()
    return np.bincount(codes, minlength=rows * k * k).reshape(rows, k, k).astype(np.float64)


def _kappa(
    confusion: npt.NDArray[np.float64], disagreement: npt.NDArray[np.float64]
) -> npt.NDArray[np.float64]:
    """Kappa for a stack of confusion matrices with shape (rows, k, k). NaN where undefined."""
    totals = confusion.sum(axis=(1, 2))
    observed = (confusion * disagreement).sum(axis=(1, 2)) / totals
    judge_marginal = confusion.sum(axis=2) / totals[:, None]
    human_marginal = confusion.sum(axis=1) / totals[:, None]
    chance = judge_marginal[:, :, None] * human_marginal[:, None, :]
    expected = (chance * disagreement).sum(axis=(1, 2))
    with np.errstate(divide="ignore", invalid="ignore"):
        result: npt.NDArray[np.float64] = np.where(expected > 0, 1 - observed / expected, np.nan)
    return result


__all__ = ["Agreement", "Label", "Trust", "judge_agreement"]
