from pathlib import Path

import pytest

from signalfloor.results import ResultsFileError, load_labels, load_scores


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "results.jsonl"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_scores_by_id(tmp_path: Path) -> None:
    path = write(tmp_path, '{"id": "a", "score": 0.5}\n{"id": "b", "score": 1}\n')

    assert load_scores(path) == {"a": 0.5, "b": 1.0}


def test_skips_blank_lines_and_extra_fields(tmp_path: Path) -> None:
    path = write(tmp_path, '\n{"id": "a", "score": 0.5, "output": "hi"}\n\n')

    assert load_scores(path) == {"a": 0.5}


def test_booleans_count_as_pass_fail(tmp_path: Path) -> None:
    path = write(tmp_path, '{"id": "a", "score": true}\n{"id": "b", "score": false}\n')

    assert load_scores(path) == {"a": 1.0, "b": 0.0}


def test_numeric_ids_become_strings(tmp_path: Path) -> None:
    path = write(tmp_path, '{"id": 7, "score": 0.5}\n')

    assert load_scores(path) == {"7": 0.5}


def test_custom_field_names(tmp_path: Path) -> None:
    path = write(tmp_path, '{"case": "a", "accuracy": 0.9}\n')

    assert load_scores(path, id_key="case", score_key="accuracy") == {"a": 0.9}


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ('{"id": "a", "score": 1}\nnot json\n', r"results.jsonl:2: invalid JSON"),
        ("[1, 2]\n", r":1: expected a JSON object"),
        ('{"score": 1}\n', r":1: missing field 'id'"),
        ('{"id": "a"}\n', r":1: missing field 'score'"),
        ('{"id": "a", "score": "high"}\n', r":1: 'score' must be a number, got 'high'"),
        ('{"id": "a", "score": null}\n', r":1: 'score' must be a number, got None"),
        ('{"id": "a", "score": 1}\n{"id": "a", "score": 0}\n', r":2: duplicate case id 'a'"),
        ("\n\n", r"no results found"),
    ],
)
def test_bad_files_report_file_and_line(tmp_path: Path, text: str, message: str) -> None:
    with pytest.raises(ResultsFileError, match=message):
        load_scores(write(tmp_path, text))


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ResultsFileError, match="cannot read file"):
        load_scores(tmp_path / "nope.jsonl")


def test_loads_labels_of_any_simple_type(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        '{"id": "a", "label": "good"}\n{"id": "b", "label": 4}\n{"id": "c", "label": true}\n',
    )

    assert load_labels(path) == {"a": "good", "b": 4, "c": True}


def test_labels_with_custom_field_names(tmp_path: Path) -> None:
    path = write(tmp_path, '{"case": "a", "verdict": "bad"}\n')

    assert load_labels(path, id_key="case", label_key="verdict") == {"a": "bad"}


@pytest.mark.parametrize("bad", ["null", "[1]", '{"x": 1}'])
def test_labels_reject_non_scalar_values(tmp_path: Path, bad: str) -> None:
    path = write(tmp_path, f'{{"id": "a", "label": {bad}}}\n')

    with pytest.raises(ResultsFileError, match="'label' must be a number, boolean or string"):
        load_labels(path)
