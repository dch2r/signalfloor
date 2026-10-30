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

    from_cases = math.sqrt(2 * (1 / 6) / 3)
    # Run means 2/3 and 1/3: their standard deviation times sqrt(2) is the gap, 1/3.
    from_runs = 1 / 3
    assert result.noise_floor_cases == pytest.approx(from_cases)
    assert result.noise_band_cases == pytest.approx(1.959964 * from_cases, rel=1e-5)
    assert result.noise_floor_runs == pytest.approx(from_runs)
    # Two runs leave one degree of freedom, so the t multiplier is 12.706.
    assert result.noise_band_runs == pytest.approx(12.7062 * from_runs, rel=1e-4)
    assert result.noise_floor == pytest.approx(max(from_cases, from_runs))
    assert result.noise_band == pytest.approx(result.noise_band_runs)


def test_runs_that_move_together_widen_the_band() -> None:
    # 100 cases that all flip together across four runs. Treating the cases as independent
    # gives a band of 0.16 while the run means swing between 0 and 1.
    runs = [run([float(r % 2)] * 100) for r in range(4)]

    result = find_flaky(runs)

    assert result.noise_band_cases == pytest.approx(0.16, abs=0.01)
    assert result.noise_floor_runs == pytest.approx(math.sqrt(2) * np.std([0, 1, 0, 1], ddof=1))
    assert result.noise_band > 1


def test_band_covers_reruns_when_runs_share_a_shift() -> None:
    # Each run adds the same random shift to every case's pass rate, the way a model or judge
    # change between runs would. Estimate the band from 5 runs, then check how often a fresh
    # pair of runs stays inside it. A 95% band should hold about 95% of the time.
    rng = np.random.default_rng(7)
    n_cases, trials = 200, 300
    base = rng.uniform(0.2, 0.8, n_cases)

    def one_run() -> dict[str, float]:
        p = np.clip(base + rng.normal(0, 0.05), 0, 1)
        return run(list((rng.random(n_cases) < p).astype(float)))

    held_combined = held_cases_only = 0
    for _ in range(trials):
        result = find_flaky([one_run() for _ in range(5)])
        a, b = one_run(), one_run()
        gap = abs(np.mean(list(a.values())) - np.mean(list(b.values())))
        held_combined += int(gap <= result.noise_band)
        held_cases_only += int(gap <= result.noise_band_cases)

    # Measured: 97% for the combined band, 71% for the cases only band. The cases only band
    # badly undercovers, which is the bug the run estimate fixes.
    assert held_combined / trials >= 0.9
    assert held_cases_only / trials < 0.8


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


def test_independent_cases_still_get_a_band_that_covers() -> None:
    # Without a shared shift the cases estimate is right on its own. The combined band is
    # wider, about 1.3 times in this setup, which is the cost of guarding against shared shifts
    # with only 5 runs. It must still cover, and not by an absurd margin.
    rng = np.random.default_rng(3)
    n_cases, trials = 200, 300
    base = rng.uniform(0.2, 0.8, n_cases)

    def one_run() -> dict[str, float]:
        return run(list((rng.random(n_cases) < base).astype(float)))

    held = 0
    widths = []
    for _ in range(trials):
        result = find_flaky([one_run() for _ in range(5)])
        a, b = one_run(), one_run()
        held += int(abs(np.mean(list(a.values())) - np.mean(list(b.values()))) <= result.noise_band)
        widths.append(result.noise_band / result.noise_band_cases)

    assert held / trials >= 0.93
    assert float(np.median(widths)) < 2
