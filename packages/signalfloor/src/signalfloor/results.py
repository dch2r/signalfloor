"""Load eval results from JSON Lines files.

Each non-empty line is one test case, for example:

    {"id": "q-001", "score": 0.85}
    {"id": "q-002", "label": "good"}

Scores must be numbers or booleans. true counts as 1 and false as 0, so pass/fail results
work as they are. Labels can also be strings.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

from signalfloor.calibration import Label

T = TypeVar("T")


class ResultsFileError(ValueError):
    """A results file could not be read or has a bad line."""


def load_scores(
    path: str | Path, *, id_key: str = "id", score_key: str = "score"
) -> dict[str, float]:
    def as_score(value: object) -> float | None:
        return float(value) if isinstance(value, int | float) else None

    return _load(path, id_key, score_key, as_score, "a number")


def load_labels(
    path: str | Path, *, id_key: str = "id", label_key: str = "label"
) -> dict[str, Label]:
    def as_label(value: object) -> Label | None:
        return value if isinstance(value, str | int | float) else None

    return _load(path, id_key, label_key, as_label, "a number, boolean or string")


def _load(
    path: str | Path,
    id_key: str,
    value_key: str,
    convert: Callable[[object], T | None],
    expected: str,
) -> dict[str, T]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ResultsFileError(f"{path}: cannot read file ({e.strerror})") from e

    values: dict[str, T] = {}
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path}:{line_no}"

        try:
            record = json.loads(line)
        except json.JSONDecodeError as e:
            raise ResultsFileError(f"{where}: invalid JSON ({e.msg})") from e
        if not isinstance(record, dict):
            raise ResultsFileError(f"{where}: expected a JSON object")

        for key in (id_key, value_key):
            if key not in record:
                raise ResultsFileError(f"{where}: missing field '{key}'")

        case_id = str(record[id_key])
        value = convert(record[value_key])
        if value is None:
            raise ResultsFileError(
                f"{where}: '{value_key}' must be {expected}, got {record[value_key]!r}"
            )
        if case_id in values:
            raise ResultsFileError(f"{where}: duplicate case id '{case_id}'")

        values[case_id] = value

    if not values:
        raise ResultsFileError(f"{path}: no results found")
    return values
