import pytest

from signalfloor_agent.scoring import exact_match, f1, normalize_answer


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The United States", "united states"),
        ("  an Apple,  a day!  ", "apple day"),
        ("Theatre", "theatre"),
        ("U.S.A.", "usa"),
    ],
)
def test_normalize_answer(text: str, expected: str) -> None:
    assert normalize_answer(text) == expected


def test_exact_match_ignores_case_articles_and_punctuation() -> None:
    assert exact_match("the Eiffel Tower.", "Eiffel tower") == 1.0
    assert exact_match("Eiffel", "Eiffel Tower") == 0.0


def test_f1_gives_partial_credit() -> None:
    # 1 shared word: precision 1/1, recall 1/2, F1 2/3.
    assert f1("Eiffel", "Eiffel Tower") == pytest.approx(2 / 3)
    assert f1("Paris France", "Paris") == pytest.approx(2 / 3)


def test_f1_counts_repeated_words_once_per_match() -> None:
    # Prediction repeats "new" but gold has it once, so only one counts.
    assert f1("new new york", "new york") == pytest.approx(0.8)


def test_f1_is_zero_with_no_overlap() -> None:
    assert f1("London", "Paris") == 0.0
    assert f1("", "Paris") == 0.0


def test_yes_no_answers_are_all_or_nothing() -> None:
    assert f1("yes", "yes") == 1.0
    assert f1("yes", "no") == 0.0
    assert f1("yes they are", "yes") == 0.0
    assert f1("no", "no way") == 0.0
