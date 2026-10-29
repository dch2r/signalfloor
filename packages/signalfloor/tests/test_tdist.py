import pytest

from signalfloor._tdist import _incomplete_beta, t_quantile


@pytest.mark.parametrize(
    ("p", "df", "expected"),
    [
        # From a standard t table.
        (0.975, 1, 12.7062),
        (0.975, 2, 4.3027),
        (0.975, 3, 3.1824),
        (0.975, 10, 2.2281),
        (0.975, 30, 2.0423),
        (0.95, 5, 2.0150),
        (0.995, 4, 4.6041),
        (0.975, 1000, 1.9623),
    ],
)
def test_matches_the_t_table(p: float, df: int, expected: float) -> None:
    assert t_quantile(p, df) == pytest.approx(expected, abs=1e-3)


def test_median_is_zero() -> None:
    assert t_quantile(0.5, 3) == 0


@pytest.mark.parametrize(("p", "df"), [(0.4, 3), (1.0, 3), (0.975, 0)])
def test_rejects_bad_arguments(p: float, df: int) -> None:
    with pytest.raises(ValueError):
        t_quantile(p, df)


def test_incomplete_beta_edges() -> None:
    assert _incomplete_beta(0, 2, 3) == 0
    assert _incomplete_beta(1, 2, 3) == 1
    # I_x(1, 1) is x.
    assert _incomplete_beta(0.3, 1, 1) == pytest.approx(0.3)
    assert _incomplete_beta(0.9, 1, 1) == pytest.approx(0.9)
