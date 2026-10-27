from collections.abc import Sequence

import numpy as np
import pytest

from signalfloor._pairing import PairingError
from signalfloor.calibration import Label, Trust, judge_agreement


def labels(values: Sequence[Label]) -> dict[str, Label]:
    return {f"case-{i:04d}": v for i, v in enumerate(values)}


# Reference values below were computed with scikit-learn's cohen_kappa_score.
RATINGS_JUDGE: list[Label] = [1, 2, 3, 4, 5, 5, 4, 3, 2, 1, 3, 3]
RATINGS_HUMAN: list[Label] = [1, 2, 3, 5, 5, 4, 4, 2, 2, 1, 4, 3]


def test_kappa_matches_textbook_example() -> None:
    # 50 cases: both yes 20, judge yes human no 5, judge no human yes 10, both no 15.
    judge = ["yes"] * 25 + ["no"] * 25
    human = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15

    result = judge_agreement(labels(judge), labels(human), n_resamples=200, seed=0)

    assert result.kappa == pytest.approx(0.4)
    assert result.raw_agreement == pytest.approx(0.7)
    assert result.categories == ("no", "yes")
    assert result.judge_bias is None


@pytest.mark.parametrize(
    ("weights", "expected"),
    [(None, 0.5862068965517241), ("linear", 0.7777777777777778), ("quadratic", 0.9047619047619048)],
)
def test_weighted_kappa_matches_reference(weights: str | None, expected: float) -> None:
    result = judge_agreement(
        labels(RATINGS_JUDGE),
        labels(RATINGS_HUMAN),
        weights=weights,  # type: ignore[arg-type]
        n_resamples=200,
        seed=0,
    )

    assert result.kappa == pytest.approx(expected)
    assert result.weights == weights


def test_always_pass_judge_scores_high_agreement_but_zero_kappa() -> None:
    # The reason kappa exists: 90% raw agreement from a judge that learned nothing.
    human = [True] * 90 + [False] * 10
    judge = [True] * 100

    result = judge_agreement(labels(judge), labels(human), seed=0)

    assert result.raw_agreement == pytest.approx(0.9)
    assert result.kappa == pytest.approx(0.0)
    assert result.verdict is Trust.UNTRUSTED


def test_good_judge_on_many_cases_is_trusted() -> None:
    rng = np.random.default_rng(0)
    human = list(rng.integers(1, 6, size=400))
    judge = [h if rng.random() < 0.9 else int(rng.integers(1, 6)) for h in human]

    result = judge_agreement(labels(judge), labels(human), seed=0)

    assert result.verdict is Trust.TRUSTED
    assert result.threshold <= result.ci_low <= result.kappa <= result.ci_high


def test_good_judge_on_few_cases_is_inconclusive() -> None:
    # Same quality judge, but 15 labels are not enough to be sure.
    human: list[Label] = [1, 0, 1, 1, 0, 1, 0, 0, 1, 1, 0, 1, 0, 1, 1]
    judge = list(human)
    judge[0], judge[1] = 0, 1

    result = judge_agreement(labels(judge), labels(human), seed=0)

    assert result.kappa > 0.6
    assert result.verdict is Trust.INCONCLUSIVE
    assert result.ci_low < 0.6 <= result.ci_high


def test_lenient_judge_has_positive_bias() -> None:
    human: list[Label] = [3, 3, 4, 2, 5, 1, 3, 4]
    judge: list[Label] = [4, 4, 5, 3, 5, 2, 4, 5]

    result = judge_agreement(labels(judge), labels(human), weights="linear", seed=0)

    assert result.judge_bias == pytest.approx(7 / 8)


def test_booleans_line_up_with_numbers() -> None:
    judge: list[Label] = [True, False, True, False]
    human: list[Label] = [1, 0, 1, 0]

    result = judge_agreement(labels(judge), labels(human), n_resamples=200, seed=0)

    assert result.kappa == 1.0
    assert result.categories == (0, 1)


def test_same_seed_gives_same_result() -> None:
    a = judge_agreement(labels(RATINGS_JUDGE), labels(RATINGS_HUMAN), seed=7)
    b = judge_agreement(labels(RATINGS_JUDGE), labels(RATINGS_HUMAN), seed=7)

    assert a == b


def test_cases_must_match() -> None:
    with pytest.raises(PairingError, match="judge and human must contain the same cases"):
        judge_agreement({"a": 1, "b": 0}, {"a": 1, "c": 0})


def test_single_shared_label_is_undefined() -> None:
    with pytest.raises(ValueError, match="kappa is undefined"):
        judge_agreement(labels(["good"] * 5), labels(["good"] * 5))


def test_weighted_kappa_needs_numbers() -> None:
    with pytest.raises(ValueError, match="weighted kappa needs numeric labels"):
        judge_agreement(labels(["a", "b"]), labels(["b", "a"]), weights="linear")


def test_mixed_label_types_are_rejected() -> None:
    with pytest.raises(ValueError, match="all numbers or all strings"):
        judge_agreement(labels(["good", "bad"]), labels([1, 0]))


def test_rejects_unsupported_label_types() -> None:
    with pytest.raises(ValueError, match="labels must be numbers, booleans or strings"):
        judge_agreement({"a": None, "b": 1}, {"a": 0, "b": 1})  # type: ignore[dict-item]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"confidence": 1.0}, "confidence"),
        ({"threshold": 1.5}, "threshold"),
        ({"n_resamples": 0}, "n_resamples"),
    ],
)
def test_rejects_bad_options(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        judge_agreement(labels([1, 0]), labels([1, 0]), **kwargs)  # type: ignore[arg-type]


def test_decimal_ratings_work_with_weights() -> None:
    judge: list[Label] = [np.float64(1.5), 2.0, 2.5, 2.0]
    human: list[Label] = [1.5, 2.0, 2.5, 2.5]

    result = judge_agreement(labels(judge), labels(human), weights="linear", seed=0)

    assert result.categories == (1.5, 2.0, 2.5)
    assert type(result.categories[0]) is float
    assert 0 < result.kappa < 1


def test_weighted_kappa_with_one_shared_label_is_undefined() -> None:
    with pytest.raises(ValueError, match="kappa is undefined"):
        judge_agreement(labels([3, 3, 3]), labels([3, 3, 3]), weights="quadratic")
