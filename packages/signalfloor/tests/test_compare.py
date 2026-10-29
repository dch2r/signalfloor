import math

import numpy as np
import pytest

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
    base = rng.random(3_000)
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


def test_false_alarm_rate_matches_confidence_level() -> None:
    # When nothing really changed, a 95% interval should exclude zero about 5% of the time.
    # 400 trials gives a standard error of about 1.1 points, so 2% to 9% is a safe band.
    rng = np.random.default_rng(5)
    trials, n_cases = 400, 100
    alarms = 0
    for t in range(trials):
        base = rng.normal(0.7, 0.15, size=n_cases)
        cand = base + rng.normal(0, 0.1, size=n_cases)  # same quality, run-to-run noise only
        result = paired_bootstrap(run(list(base)), run(list(cand)), n_resamples=2_000, seed=t)
        alarms += result.verdict is not Verdict.INCONCLUSIVE

    assert 0.02 <= alarms / trials <= 0.09


def test_pairing_catches_a_drop_that_case_difficulty_would_hide() -> None:
    # Cases range from very easy to very hard, so raw scores vary a lot between cases.
    # The candidate is a little worse on every case. Comparing the two averages on their own
    # would drown that in the spread between cases, but paired differences remove it.
    rng = np.random.default_rng(6)
    difficulty = rng.uniform(0.0, 1.0, size=100)
    base = difficulty + rng.normal(0, 0.01, size=100)
    cand = difficulty - 0.02 + rng.normal(0, 0.01, size=100)

    result = paired_bootstrap(run(list(base)), run(list(cand)), seed=0)
    assert result.verdict is Verdict.REGRESSION

    # Sanity check that an unpaired view really could not tell: the two separate 95%
    # intervals for the means overlap heavily.
    half_width = 1.96 * difficulty.std(ddof=1) / math.sqrt(100)
    assert abs(base.mean() - cand.mean()) < half_width


def test_inconclusive_reports_the_largest_drop_it_cannot_rule_out() -> None:
    base = {f"c{i}": 0.5 for i in range(8)}
    noisy = {f"c{i}": 0.8 if i % 2 else 0.2 for i in range(8)}

    result = paired_bootstrap(base, noisy, seed=0)

    assert result.verdict is Verdict.INCONCLUSIVE
    # Eight cases could also miss a change that broke over a third of all cases.
    unseen = result.unseen_share
    assert unseen == pytest.approx(1 - 0.025 ** (1 / 8))
    expected = -(1 - unseen) * result.ci_low + unseen
    assert result.largest_drop_not_ruled_out == pytest.approx(expected)
    assert result.largest_drop_not_ruled_out > -result.ci_low
    assert result.decision is None


def test_largest_drop_is_zero_for_a_proven_improvement() -> None:
    base = {f"c{i}": 0.5 for i in range(50)}
    better = {f"c{i}": 0.7 for i in range(50)}

    assert paired_bootstrap(base, better, seed=0).largest_drop_not_ruled_out == 0


def test_a_zero_margin_passes_only_a_clear_improvement() -> None:
    same = {f"c{i}": 0.5 for i in range(20)}
    noisy = {f"c{i}": 0.6 if i % 2 else 0.4 for i in range(20)}
    better = {f"c{i}": 0.9 for i in range(20)}

    # Identical runs show no drop, but 20 cases could have missed one.
    assert paired_bootstrap(same, same, seed=0, margin=0).decision is Decision.NEEDS_MORE_EVIDENCE
    assert paired_bootstrap(same, noisy, seed=0, margin=0).decision is Decision.NEEDS_MORE_EVIDENCE
    assert paired_bootstrap(same, better, seed=0, margin=0).decision is Decision.PASS


def test_a_regression_hidden_in_cases_the_eval_never_drew() -> None:
    # The study in studies/validation found this. A change broke 4 of 100 questions and a
    # 20 case eval drew none of them, so every difference is zero and the interval is [0, 0].
    # That used to pass a margin of 0.02 although the real drop is 0.04.
    sample = {f"c{i}": 1.0 if i < 5 else 0.0 for i in range(20)}

    result = paired_bootstrap(sample, sample, seed=0, margin=0.02)

    assert (result.ci_low, result.ci_high) == (0, 0)
    assert result.decision is Decision.NEEDS_MORE_EVIDENCE
    assert result.largest_drop_not_ruled_out > 0.04


def test_enough_cases_pass_a_margin_and_one_fewer_does_not() -> None:
    needed = cases_needed(0.02)

    def decide(n: int) -> Decision | None:
        same = {f"c{i}": float(i % 2) for i in range(n)}
        return paired_bootstrap(same, same, seed=0, margin=0.02).decision

    assert decide(needed) is Decision.PASS
    assert decide(needed - 1) is Decision.NEEDS_MORE_EVIDENCE


@pytest.mark.parametrize(
    ("margin", "kwargs", "expected"),
    [
        (0.02, {}, 183),
        (0.05, {}, 72),
        (0.1, {}, 36),
        (0.05, {"confidence": 0.9}, 59),
        (5.0, {"max_case_drop": 100.0}, 72),
        (1.0, {}, 1),
    ],
)
def test_cases_needed(margin: float, kwargs: dict[str, float], expected: int) -> None:
    assert cases_needed(margin, **kwargs) == expected


def test_no_number_of_cases_passes_a_zero_margin() -> None:
    with pytest.raises(ValueError, match="margin of 0 never passes"):
        cases_needed(0)


def test_scores_outside_0_to_1_use_the_range_seen() -> None:
    base = {f"c{i}": float(i) for i in range(50)}

    result = paired_bootstrap(base, base, seed=0)

    assert result.max_case_drop == 49
    assert paired_bootstrap({"a": 0.2, "b": 0.9}, {"a": 0.2, "b": 0.9}).max_case_drop == 1


@pytest.mark.parametrize("margin", [-0.01, float("nan"), float("inf")])
def test_bad_margins_are_rejected(margin: float) -> None:
    same = {"a": 1.0, "b": 0.0}

    with pytest.raises(ValueError, match="margin"):
        paired_bootstrap(same, same, margin=margin)
