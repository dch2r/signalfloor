import itertools
import math
from collections.abc import Callable

import numpy as np
import numpy.typing as npt
import pytest

from signalfloor._betting import rejects
from signalfloor.compare import Decision, PairingError, Verdict, cases_needed, paired_bootstrap


def run(scores: list[float]) -> dict[str, float]:
    return {f"case-{i:04d}": s for i, s in enumerate(scores)}


def test_identical_runs_are_inconclusive() -> None:
    scores = run([0.1, 0.5, 0.9, 0.3, 0.7])
    result = paired_bootstrap(scores, scores, seed=0)

    assert result.delta == 0
    assert result.ci_low == result.ci_high == 0
    assert result.verdict is Verdict.INCONCLUSIVE


def test_clear_drop_is_a_regression() -> None:
    rng = np.random.default_rng(1)
    base = rng.uniform(0.6, 1.0, size=200)
    cand = base - 0.2 + rng.normal(0, 0.05, size=200)

    result = paired_bootstrap(run(list(base)), run(list(cand)), seed=0)

    assert result.verdict is Verdict.REGRESSION
    assert result.ci_low < result.delta < result.ci_high < 0
    assert result.delta == pytest.approx(-0.2, abs=0.02)


def test_clear_gain_is_an_improvement() -> None:
    rng = np.random.default_rng(2)
    base = rng.uniform(0.0, 0.5, size=200)
    cand = base + 0.1 + rng.normal(0, 0.05, size=200)

    result = paired_bootstrap(run(list(base)), run(list(cand)), seed=0)

    assert result.verdict is Verdict.IMPROVEMENT
    assert result.ci_low > 0


def test_small_noisy_change_on_few_cases_is_not_called() -> None:
    # Pass/fail scores on 20 cases: candidate fails one more case than baseline.
    base = run([1.0] * 16 + [0.0] * 4)
    cand = run([1.0] * 15 + [0.0] * 5)

    result = paired_bootstrap(base, cand, seed=0)

    assert result.delta == pytest.approx(-0.05)
    assert result.verdict is Verdict.INCONCLUSIVE


def test_cases_are_paired_by_id_not_by_order() -> None:
    base = {"a": 0.0, "b": 1.0, "c": 0.5}
    cand = {"c": 0.5, "a": 0.0, "b": 1.0}

    result = paired_bootstrap(base, cand, seed=0)

    assert result.delta == 0
    assert result.verdict is Verdict.INCONCLUSIVE


def test_same_seed_gives_same_interval() -> None:
    rng = np.random.default_rng(3)
    base, cand = run(list(rng.random(50))), run(list(rng.random(50)))

    first = paired_bootstrap(base, cand, seed=42)
    second = paired_bootstrap(base, cand, seed=42)

    assert first == second


def test_reports_means_and_sizes() -> None:
    result = paired_bootstrap(run([1.0, 0.0]), run([1.0, 1.0]), n_resamples=500, seed=0)

    assert result.baseline_mean == 0.5
    assert result.candidate_mean == 1.0
    assert result.n_cases == 2
    assert result.n_resamples == 500
    assert result.confidence == 0.95


def test_large_suite_is_processed_in_chunks() -> None:
    # 5,000 resamples x 3,000 cases would be 15M values if done at once.
    rng = np.random.default_rng(4)
    base = rng.uniform(0.01, 1, size=3_000)
    result = paired_bootstrap(run(list(base)), run(list(base - 0.01)), n_resamples=5_000, seed=0)

    assert result.verdict is Verdict.REGRESSION


def test_mismatched_cases_raise_with_examples() -> None:
    base = {"a": 1.0, "b": 1.0, "c": 1.0}
    cand = {"a": 1.0, "b": 1.0, "d": 1.0}

    with pytest.raises(PairingError, match=r"1 only in baseline \(e.g. c\).*1 only in candidate"):
        paired_bootstrap(base, cand)


@pytest.mark.parametrize("bad", [math.nan, math.inf])
def test_non_finite_scores_raise(bad: float) -> None:
    with pytest.raises(ValueError, match="candidate has non-finite scores for cases b"):
        paired_bootstrap({"a": 1.0, "b": 1.0}, {"a": 1.0, "b": bad})


def test_needs_at_least_two_cases() -> None:
    with pytest.raises(ValueError, match="at least 2 cases"):
        paired_bootstrap({"a": 1.0}, {"a": 0.0})


@pytest.mark.parametrize("confidence", [0.0, 1.0, -0.5, 95])
def test_rejects_invalid_confidence(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        paired_bootstrap(run([0.0, 1.0]), run([0.0, 1.0]), confidence=confidence)


def test_rejects_non_positive_resamples() -> None:
    with pytest.raises(ValueError, match="n_resamples"):
        paired_bootstrap(run([0.0, 1.0]), run([0.0, 1.0]), n_resamples=0)


def test_false_alarms_stay_within_the_confidence_level() -> None:
    # When nothing really changed, a 95% interval should exclude zero at most 5% of the time.
    # The bootstrap interval alone is close to that. The bounds are wider, so they alarm less.
    rng = np.random.default_rng(5)
    trials, n_cases = 400, 100
    interval_alarms = bound_alarms = 0
    for t in range(trials):
        base = np.clip(rng.normal(0.7, 0.15, size=n_cases), 0, 1)
        cand = np.clip(base + rng.normal(0, 0.1, size=n_cases), 0, 1)  # run-to-run noise only
        result = paired_bootstrap(run(list(base)), run(list(cand)), n_resamples=2_000, seed=t)
        interval_alarms += not result.ci_low <= 0 <= result.ci_high
        bound_alarms += result.verdict is not Verdict.INCONCLUSIVE

    assert 0.02 <= interval_alarms / trials <= 0.09
    assert bound_alarms / trials <= interval_alarms / trials


def test_pairing_catches_a_drop_that_case_difficulty_would_hide() -> None:
    # Cases range from very easy to very hard, so raw scores vary a lot between cases.
    # The candidate is a little worse on every case. Comparing the two averages on their own
    # would drown that in the spread between cases, but paired differences remove it.
    # 300 cases, because the bounds can't call any change smaller than about 3.7 / n.
    rng = np.random.default_rng(6)
    n = 300
    difficulty = rng.uniform(0.05, 0.95, size=n)
    base = difficulty + rng.normal(0, 0.01, size=n)
    cand = difficulty - 0.02 + rng.normal(0, 0.01, size=n)

    result = paired_bootstrap(run(list(base)), run(list(cand)), seed=0)
    assert result.verdict is Verdict.REGRESSION

    # Sanity check that an unpaired view really could not tell: the two separate 95%
    # intervals for the means overlap heavily.
    half_width = 1.96 * difficulty.std(ddof=1) / math.sqrt(n)
    assert abs(base.mean() - cand.mean()) < half_width


def test_inconclusive_reports_the_largest_drop_it_cannot_rule_out() -> None:
    base = {f"c{i}": 0.5 for i in range(8)}
    noisy = {f"c{i}": 0.8 if i % 2 else 0.2 for i in range(8)}

    result = paired_bootstrap(base, noisy, seed=0)

    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.largest_drop_not_ruled_out == pytest.approx(-result.bound_low)
    # Eight cases are little evidence, so the bounds reach well past the bootstrap interval.
    assert result.bound_low < result.ci_low
    assert result.decision is None


def test_largest_drop_is_zero_for_a_proven_improvement() -> None:
    base = {f"c{i}": 0.5 for i in range(50)}
    better = {f"c{i}": 0.7 for i in range(50)}

    assert paired_bootstrap(base, better, seed=0).largest_drop_not_ruled_out == 0


def test_a_zero_margin_passes_only_a_clear_improvement() -> None:
    same = {f"c{i}": 0.5 for i in range(20)}
    noisy = {f"c{i}": 0.6 if i % 2 else 0.4 for i in range(20)}
    better = {f"c{i}": 1.0 for i in range(20)}

    assert paired_bootstrap(same, same, seed=0, margin=0).decision is Decision.NEEDS_MORE_EVIDENCE
    assert paired_bootstrap(same, noisy, seed=0, margin=0).decision is Decision.NEEDS_MORE_EVIDENCE
    assert paired_bootstrap(same, better, seed=0, margin=0).decision is Decision.PASS


def test_a_regression_hidden_in_cases_the_eval_never_drew() -> None:
    # A change broke 4 of 100 questions and a 20 case eval drew none of them, so every
    # difference is zero and the bootstrap interval is [0, 0]. That used to pass 0.02.
    sample = {f"c{i}": 1.0 if i < 5 else 0.0 for i in range(20)}

    result = paired_bootstrap(sample, sample, seed=0, margin=0.02)

    assert (result.ci_low, result.ci_high) == (0, 0)
    assert result.decision is Decision.NEEDS_MORE_EVIDENCE
    assert result.largest_drop_not_ruled_out > 0.04


def test_cases_needed_is_the_count_for_an_unchanged_eval() -> None:
    needed = cases_needed(0.02)
    assert needed is not None

    def decide(n: int) -> Decision | None:
        same = {f"c{i}": float(i % 2) for i in range(n)}
        return paired_bootstrap(same, same, seed=0, margin=0.02).decision

    assert decide(needed) is Decision.PASS
    assert decide(needed - 1) is Decision.NEEDS_MORE_EVIDENCE
    # It is not a floor for every eval: 20 clear gains pass the same margin.
    gains = paired_bootstrap(
        {f"c{i}": 0.0 for i in range(20)}, {f"c{i}": 1.0 for i in range(20)}, margin=0.02
    )
    assert gains.decision is Decision.PASS


@pytest.mark.parametrize(
    ("margin", "kwargs", "expected"),
    [
        (0.02, {}, 249),
        (0.05, {}, 98),
        (0.1, {}, 48),
        (5.0, {"max_case_drop": 100.0}, 98),
        (2.0, {}, 1),
    ],
)
def test_cases_needed(margin: float, kwargs: dict[str, float], expected: int) -> None:
    assert cases_needed(margin, **kwargs) == expected


def test_an_unchanged_eval_never_passes_a_zero_margin() -> None:
    with pytest.raises(ValueError, match="never passes 0"):
        cases_needed(0)


@pytest.mark.parametrize("shift", [0.0, 100.0, -7.5])
@pytest.mark.parametrize("scale", [1.0, 10.0])
def test_moving_or_stretching_the_scale_does_not_change_the_answer(
    shift: float, scale: float
) -> None:
    # The review that found this: scores of 100.5 used to pass where 0.5 did not, because
    # the score range was guessed from the scores seen.
    rng = np.random.default_rng(9)
    base = rng.uniform(0, 1, size=60)
    cand = np.clip(base - rng.choice([0.0, 0.3], size=60, p=[0.8, 0.2]), 0, 1)

    def decide(b: np.ndarray, c: np.ndarray, **kwargs: object) -> tuple[object, ...]:
        r = paired_bootstrap(run(list(b)), run(list(c)), seed=0, **kwargs)  # type: ignore[arg-type]
        return r.verdict, r.decision, round(r.largest_drop_not_ruled_out / (r.max_case_drop), 9)

    plain = decide(base, cand, margin=0.05)
    moved = decide(
        base * scale + shift,
        cand * scale + shift,
        margin=0.05 * scale,
        score_range=(shift, shift + scale),
    )
    assert moved == plain


def test_constant_scores_far_from_zero_do_not_pass() -> None:
    same = {"a": 100.5, "b": 100.5}

    result = paired_bootstrap(same, same, seed=0, margin=0, score_range=(0, 200))

    assert result.decision is Decision.NEEDS_MORE_EVIDENCE


def test_scores_outside_the_range_are_refused() -> None:
    with pytest.raises(ValueError, match=r"candidate has scores outside the score range 0 to 1"):
        paired_bootstrap({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 4.0})
    assert paired_bootstrap({"a": 4.0, "b": 2.0}, {"a": 3.0, "b": 2.0}, score_range=(1, 5))


@pytest.mark.parametrize("bad", [(1.0, 1.0), (1.0, 0.0), (0.0, math.inf), (math.nan, 1.0)])
def test_bad_score_ranges_are_refused(bad: tuple[float, float]) -> None:
    with pytest.raises(ValueError, match="score range"):
        paired_bootstrap({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}, score_range=bad)


def test_two_losses_from_an_even_population_are_not_a_regression() -> None:
    # The review that found this: half the cases go 1 -> 0, half go 0 -> 1, so nothing
    # changed on average. Two cases drawn are both losses a quarter of the time, and the
    # bootstrap interval is [-1, -1].
    result = paired_bootstrap({"a": 1, "b": 1}, {"a": 0, "b": 0}, seed=0, margin=0.02)

    assert (result.ci_low, result.ci_high) == (-1, -1)
    assert result.verdict is Verdict.INCONCLUSIVE
    assert result.decision is Decision.NEEDS_MORE_EVIDENCE


def test_six_losses_and_one_gain_are_not_a_fail() -> None:
    # The second review found this one. The rule-of-three bounds fell back to the bootstrap
    # once both extremes were seen, and failed it, which happens 6.25% of the time with
    # seven cases when nothing changed.
    base = {f"c{i}": 1.0 for i in range(6)} | {"c6": 0.0}
    cand = {f"c{i}": 0.0 for i in range(6)} | {"c6": 1.0}

    for seed in range(5):
        result = paired_bootstrap(base, cand, seed=seed, margin=0.02)
        assert result.decision is Decision.NEEDS_MORE_EVIDENCE


def exact_error_rate(
    outcomes: dict[float, float], n: int, wrong: Callable[[npt.NDArray[np.float64]], bool]
) -> float:
    """The exact chance that wrong() holds, over every sequence of n draws from outcomes.

    outcomes maps a value on the [0, 1] betting scale to its probability.
    """
    total = 0.0
    for draw in itertools.product(outcomes, repeat=n):
        if wrong(np.array(draw)):
            total += math.prod(outcomes[v] for v in draw)
    return total


# Margin 0.02 on differences between -1 and 1 is 0.01 on the [0, 1] betting scale.
FAIL_POINT = 0.5 - 0.01


def fails(x: npt.NDArray[np.float64]) -> bool:
    """The decision is fail: the whole interval sits below -margin."""
    return bool(x.mean() < FAIL_POINT and rejects(x, FAIL_POINT, 0.05))


def passes(x: npt.NDArray[np.float64]) -> bool:
    """The decision is pass: the whole interval sits at or above -margin."""
    return bool(x.mean() > FAIL_POINT and rejects(x, FAIL_POINT, 0.05))


@pytest.mark.parametrize("n", range(1, 13))
def test_exact_false_fails_when_nothing_changed(n: int) -> None:
    # Every sequence of every size from 1 to 12, not a sample. Half the cases lose and half
    # gain, so the true change is zero and any fail is wrong. A 95% interval allows 2.5%.
    even = {0.0: 0.5, 1.0: 0.5}
    sparse = {0.0: 0.1, 0.5: 0.8, 1.0: 0.1}

    assert exact_error_rate(even, n, fails) <= 0.025
    if n <= 8:
        assert exact_error_rate(sparse, n, fails) <= 0.025


@pytest.mark.parametrize("n", range(1, 13))
def test_exact_false_passes_when_a_few_cases_broke(n: int) -> None:
    # A change broke 4% of cases outright, a drop of 0.04, twice the margin. Any pass is
    # wrong. Small evals usually draw none of the broken cases, which fooled the bootstrap.
    broke = {0.5: 0.96, 0.0: 0.04}

    assert exact_error_rate(broke, n, passes) <= 0.025


def test_missing_cases_count_as_anything_they_could_have_been() -> None:
    # 190 cases match and 10 of a 200 case suite are missing from the candidate. If it
    # crashed on them, the drop is 0.05. The shared cases alone would pass 0.02.
    same = {f"c{i}": 1.0 for i in range(190)}

    strict = paired_bootstrap(same, same, seed=0, margin=0.02, missing_cases=10)
    loose = paired_bootstrap(same, same, seed=0, margin=0.1, missing_cases=10)

    assert strict.decision is Decision.NEEDS_MORE_EVIDENCE
    assert strict.largest_drop_not_ruled_out > 0.05
    assert loose.decision is Decision.PASS
    with pytest.raises(ValueError, match="missing_cases"):
        paired_bootstrap(same, same, missing_cases=-1)


def test_tiny_margins_do_not_crash() -> None:
    # This used to divide by log(1 - 1e-20), which is 0 in floating point.
    assert cases_needed(1e-20) is None


@pytest.mark.parametrize("margin", [-0.01, float("nan"), float("inf")])
def test_bad_margins_are_rejected(margin: float) -> None:
    same = {"a": 1.0, "b": 0.0}

    with pytest.raises(ValueError, match="margin"):
        paired_bootstrap(same, same, margin=margin)
