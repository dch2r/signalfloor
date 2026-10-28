"""Run the agent over a set of questions and write one JSON line per question.

The output is a signalfloor results file. Each line has the case id and its F1 as "score",
plus exact match, how many searches ran, how much of the supporting evidence the agent
retrieved, and how long it took. Pass two of these files to `signalfloor compare`.

Runs resume. Questions already in the output file are skipped, so a run that was stopped
part way can be finished by running the same command again.

The files never contain question or gold answer text. Those belong to HotpotQA, which has its
own license, and can be looked up by id.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from signalfloor_agent.agent import Agent
from signalfloor_agent.data import Question
from signalfloor_agent.scoring import exact_match, f1


@dataclass(frozen=True)
class CaseResult:
    id: str
    score: float
    exact_match: float
    answer: str
    searches: int
    supporting_recall: float
    hit_search_limit: bool
    seconds: float


@dataclass(frozen=True)
class Summary:
    cases: int
    mean_f1: float
    mean_exact_match: float
    mean_searches: float
    mean_supporting_recall: float
    hit_search_limit: int
    total_seconds: float


def evaluate_case(agent: Agent, question: Question) -> CaseResult:
    start = time.perf_counter()
    result = agent.answer(question.question)
    seconds = time.perf_counter() - start
    supporting = set(question.supporting_titles)
    return CaseResult(
        id=question.id,
        score=f1(result.answer, question.answer),
        exact_match=exact_match(result.answer, question.answer),
        answer=result.answer,
        searches=len(result.searches),
        supporting_recall=len(supporting & set(result.retrieved_titles)) / len(supporting),
        hit_search_limit=result.hit_search_limit,
        seconds=round(seconds, 2),
    )


def run_eval(
    agent: Agent,
    questions: Sequence[Question],
    out: Path,
    *,
    progress: Callable[[str], None] | None = None,
) -> list[CaseResult]:
    """Evaluate every question not already in out, appending each result as it finishes."""
    done = {r.id: r for r in read_results(out)} if out.exists() else {}
    out.parent.mkdir(parents=True, exist_ok=True)

    with out.open("a", encoding="utf-8") as f:
        for i, q in enumerate(questions, start=1):
            if q.id in done:
                continue
            result = evaluate_case(agent, q)
            f.write(json.dumps(asdict(result)) + "\n")
            f.flush()
            done[q.id] = result
            if progress:
                progress(
                    f"[{i}/{len(questions)}] f1 {result.score:.2f} "
                    f"searches {result.searches} {result.seconds:.0f}s  {result.answer[:60]!r}"
                )
    return [done[q.id] for q in questions]


def read_results(path: Path) -> list[CaseResult]:
    return [
        CaseResult(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def summarize(results: Sequence[CaseResult]) -> Summary:
    if not results:
        raise ValueError("no results to summarize")
    n = len(results)
    return Summary(
        cases=n,
        mean_f1=sum(r.score for r in results) / n,
        mean_exact_match=sum(r.exact_match for r in results) / n,
        mean_searches=sum(r.searches for r in results) / n,
        mean_supporting_recall=sum(r.supporting_recall for r in results) / n,
        hit_search_limit=sum(r.hit_search_limit for r in results),
        total_seconds=sum(r.seconds for r in results),
    )
