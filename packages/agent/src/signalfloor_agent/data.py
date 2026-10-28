"""Load HotpotQA questions and build the passage corpus the agent searches.

HotpotQA (https://hotpotqa.github.io) is licensed CC BY-SA 4.0. It is downloaded at run time
and cached locally, never committed to this repository.

Each question comes with 10 Wikipedia passages: the 2 that hold the answer and 8 distractors.
We pool the passages of every loaded question into one corpus, so the agent has to find the
right passages among about a thousand instead of just its own ten.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

ROWS_URL = "https://datasets-server.huggingface.co/rows"
DATASET = {"dataset": "hotpotqa/hotpot_qa", "config": "distractor", "split": "validation"}
PAGE_SIZE = 100  # the most rows the API returns per request


class DataError(RuntimeError):
    """The dataset could not be downloaded or parsed."""


@dataclass(frozen=True)
class Passage:
    title: str
    text: str


@dataclass(frozen=True)
class Question:
    id: str
    question: str
    answer: str
    kind: str
    level: str
    supporting_titles: tuple[str, ...]
    passages: tuple[Passage, ...]


@dataclass(frozen=True)
class Dataset:
    questions: tuple[Question, ...]
    corpus: tuple[Passage, ...]


def load_hotpot(
    n: int = 100,
    *,
    offset: int = 0,
    cache_dir: Path | None = None,
    client: httpx.Client | None = None,
) -> Dataset:
    """Load n questions from the HotpotQA dev set, starting at offset."""
    if n < 1:
        raise ValueError(f"n must be positive, got {n}")
    if offset < 0:
        raise ValueError(f"offset must not be negative, got {offset}")

    cache = (cache_dir or default_cache_dir()) / f"hotpot_dev_distractor_{offset}_{n}.json"
    if cache.exists():
        rows = json.loads(cache.read_text(encoding="utf-8"))
    else:
        rows = _download(n, offset, client)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(rows), encoding="utf-8")

    questions = tuple(parse_row(row) for row in rows)
    return Dataset(questions=questions, corpus=build_corpus(questions))


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "signalfloor-agent"


def parse_row(row: Mapping[str, Any]) -> Question:
    try:
        context = row["context"]
        passages = tuple(
            Passage(title=title, text="".join(sentences).strip())
            for title, sentences in zip(context["title"], context["sentences"], strict=True)
        )
        return Question(
            id=row["id"],
            question=row["question"],
            answer=row["answer"],
            kind=row["type"],
            level=row["level"],
            supporting_titles=tuple(dict.fromkeys(row["supporting_facts"]["title"])),
            passages=passages,
        )
    except (KeyError, TypeError, ValueError) as e:
        raise DataError(f"unexpected HotpotQA row format: {e!r}") from e


def build_corpus(questions: Sequence[Question]) -> tuple[Passage, ...]:
    """Every distinct passage across the questions, one per title, sorted by title."""
    by_title: dict[str, Passage] = {}
    for q in questions:
        for p in q.passages:
            by_title.setdefault(p.title, p)
    return tuple(by_title[t] for t in sorted(by_title))


def _download(n: int, offset: int, client: httpx.Client | None) -> list[dict[str, Any]]:
    own_client = client is None
    http = client or httpx.Client(timeout=30)
    rows: list[dict[str, Any]] = []
    try:
        for start in range(offset, offset + n, PAGE_SIZE):
            length = min(PAGE_SIZE, offset + n - start)
            params = {**DATASET, "offset": str(start), "length": str(length)}
            try:
                response = http.get(ROWS_URL, params=params)
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise DataError(
                    f"could not download HotpotQA rows {start}-{start + length}: {e}"
                ) from e
            page = [item["row"] for item in response.json()["rows"]]
            if not page:
                break
            rows.extend(page)
    finally:
        if own_client:
            http.close()
    if len(rows) < n:
        raise DataError(f"asked for {n} questions from offset {offset} but only {len(rows)} exist")
    return rows
