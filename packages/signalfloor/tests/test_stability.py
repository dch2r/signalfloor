import math

import numpy as np
import pytest

from signalfloor._pairing import PairingError
from signalfloor.stability import find_flaky


def run(scores: list[float]) -> dict[str, float]:
    return {f"case-{i:03d}": s for i, s in enumerate(scores)}


def test_identical_runs_have_no_flaky_cases_and_zero_noise() -> None:
    scores = run([1.0, 0.0, 1.0, 0.5])

    result = find_flaky([scores, scores, scores])

    assert result.flaky == ()
    assert result.flaky_rate == 0
    assert result.noise_floor == 0
    assert result.noise_band == 0
    assert result.run_means == (0.625, 0.625, 0.625)


def test_flags_a_case_that_flips_between_runs() -> None:
    a = run([1.0, 1.0, 0.0, 1.0])
    b = run([1.0, 0.0, 0.0, 1.0])
    c = run([1.0, 1.0, 0.0, 1.0])

    result = find_flaky([a, b, c])

    assert [f.case_id for f in result.flaky] == ["case-001"]
    flaky = result.flaky[0]
    assert flaky.scores == (1.0, 0.0, 1.0)
    assert flaky.mean == pytest.approx(2 / 3)
    assert flaky.spread == 1.0
    assert result.flaky_rate == 0.25
    assert result.n_runs == 3
    assert result.n_cases == 4


def test_tolerance_ignores_small_wobble() -> None:
    a = run([0.80, 0.50, 0.90])
    b = run([0.85, 0.10, 0.90])

    assert [f.case_id for f in find_flaky([a, b]).flaky] == ["case-001", "case-000"]
    assert [f.case_id for f in find_flaky([a, b], tolerance=0.1).flaky] == ["case-001"]


def test_flaky_cases_sorted_by_spread_then_id() -> None:
    a = run([0.0, 0.0, 0.0, 0.0])
    b = run([0.2, 0.9, 0.2, 0.5])

    result = find_flaky([a, b])

    assert [f.case_id for f in result.flaky] == ["case-001", "case-003", "case-000", "case-002"]


def test_noise_floor_formula_on_a_small_example() -> None:
    # Case variances across the 2 runs: 0.5, 0 and 0. Mean is 1/6 and n is 3.
    a = run([1.0, 1.0, 0.0])
    b = run([0.0, 1.0, 0.0])

    result = find_flaky([a, b])

    expected = math.sqrt(2 * (1 / 6) / 3)
    assert result.noise_floor == pytest.approx(expected)
    assert result.noise_band == pytest.approx(1.959964 * expected, rel=1e-5)


def test_noise_floor_matches_how_much_identical_runs_really_move() -> None:
    # Simulate an eval where each case passes with its own fixed probability. Rerunning the
    # same eval many times shows how much the mean really moves between two runs. The noise
    # floor estimated from just 5 runs should be close to that.
    rng = np.random.default_rng(0)
    n_cases = 400
    pass_prob = rng.uniform(0.5, 1.0, size=n_cases)

    def one_run() -> dict[str, float]:
        return run(list((rng.random(n_cases) < pass_prob).astype(float)))

    estimated = find_flaky([one_run() for _ in range(5)]).noise_floor
    actual_diffs = [
        np.mean(list(one_run().values())) - np.mean(list(one_run().values())) for _ in range(2000)
    ]
    actual = float(np.std(actual_diffs))

    assert estimated == pytest.approx(actual, rel=0.15)


def test_runs_must_share_cases() -> None:
    a = run([1.0, 0.0])
    c = {"case-000": 1.0, "other": 0.0}

    with pytest.raises(PairingError, match="run 1 and run 3 must contain the same cases"):
        find_flaky([a, a, c])


def test_non_finite_scores_raise() -> None:
    with pytest.raises(ValueError, match="non-finite scores for cases case-001"):
        find_flaky([run([1.0, 1.0]), run([1.0, math.nan])])


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"tolerance": -0.1}, "tolerance"), ({"confidence": 0.0}, "confidence")],
)
def test_rejects_bad_options(kwargs: dict[str, float], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        find_flaky([run([1.0, 0.0]), run([1.0, 0.0])], **kwargs)


def test_needs_two_runs() -> None:
    with pytest.raises(ValueError, match="at least 2 runs"):
        find_flaky([run([1.0, 0.0])])
