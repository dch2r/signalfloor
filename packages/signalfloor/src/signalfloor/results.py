"""Load eval results from JSON Lines files.

Each non-empty line is one test case, for example:

    {"id": "q-001", "score": 0.85}

Scores can be numbers or booleans. true counts as 1 and false as 0, so pass/fail results
work as they are.
"""

from __future__ import annotations

import json
from pathlib import Path


class ResultsFileError(ValueError):
    """A results file could not be read or has a bad line."""


def load_scores(
    path: str | Path, *, id_key: str = "id", score_key: str = "score"
) -> dict[str, float]:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise ResultsFileError(f"{path}: cannot read file ({e.strerror})") from e

    scores: dict[str, float] = {}
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

        for key in (id_key, score_key):
            if key not in record:
                raise ResultsFileError(f"{where}: missing field '{key}'")

        case_id = str(record[id_key])
        score = record[score_key]
        if not isinstance(score, int | float):
            raise ResultsFileError(f"{where}: '{score_key}' must be a number, got {score!r}")
        if case_id in scores:
            raise ResultsFileError(f"{where}: duplicate case id '{case_id}'")

        scores[case_id] = float(score)

    if not scores:
        raise ResultsFileError(f"{path}: no results found")
    return scores
