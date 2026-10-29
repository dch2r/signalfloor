"""Upload, list, fetch, delete and compare eval runs."""

from __future__ import annotations

import math
import uuid
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from signalfloor_server.comparisons import RunNotFound, compare, diff
from signalfloor_server.db import Session
from signalfloor_server.models import CaseResult, Run
from signalfloor_server.schemas import CaseOut, ComparisonOut, RunDiffOut, RunIn, RunOut
from signalfloor_server.traces import load_spans

MAX_RESAMPLES = 100_000

router = APIRouter(prefix="/runs", tags=["runs"])


@router.post("", status_code=201)
async def create_run(body: RunIn, session: Session) -> RunOut:
    scores = [c.score for c in body.cases]
    run = Run(
        name=body.name,
        labels=body.labels,
        n_cases=len(scores),
        mean_score=math.fsum(scores) / len(scores),
    )
    session.add(run)
    await session.flush()
    await session.execute(
        insert(CaseResult),
        [
            {"run_id": run.id, "case_id": c.id, "score": c.score, "trace_id": c.trace_id}
            for c in body.cases
        ],
    )
    await session.commit()
    return RunOut.model_validate(run)


@router.get("")
async def list_runs(
    session: Session,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
    label: Annotated[
        list[str] | None, Query(description="Only runs with this label, as key=value. Repeatable.")
    ] = None,
) -> list[RunOut]:
    """Runs, newest first."""
    query = select(Run).order_by(Run.created_at.desc(), Run.id).limit(limit).offset(offset)
    if label:
        query = query.where(Run.labels.contains(_parse_labels(label)))
    runs = await session.scalars(query)
    return [RunOut.model_validate(r) for r in runs]


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, session: Session) -> RunOut:
    return RunOut.model_validate(await _get(session, run_id))


@router.get("/{run_id}/cases/{case_id}")
async def get_case(run_id: uuid.UUID, case_id: str, session: Session) -> CaseOut:
    """One case's score, with its trace if the run recorded one and the spans have arrived."""
    case = await session.get(CaseResult, (run_id, case_id))
    if case is None:
        raise HTTPException(404, f"case {case_id!r} not found in run {run_id}")
    spans = await load_spans(session, case.trace_id) if case.trace_id else []
    return CaseOut(case_id=case.case_id, score=case.score, trace_id=case.trace_id, spans=spans)


@router.delete("/{run_id}", status_code=204)
async def delete_run(run_id: uuid.UUID, session: Session) -> Response:
    await session.delete(await _get(session, run_id))
    await session.commit()
    return Response(status_code=204)


@router.get("/{baseline_id}/compare/{candidate_id}")
async def compare_runs(
    baseline_id: uuid.UUID,
    candidate_id: uuid.UUID,
    session: Session,
    confidence: Annotated[float, Query(gt=0, lt=1)] = 0.95,
    n_resamples: Annotated[int, Query(ge=100, le=MAX_RESAMPLES)] = 10_000,
    seed: Annotated[int | None, Query(ge=0)] = None,
    shared_only: Annotated[
        bool, Query(description="Compare only the cases both runs have, instead of refusing.")
    ] = False,
    margin: Annotated[
        float | None,
        Query(ge=0, description="The largest drop you accept. Adds a pass or fail decision."),
    ] = None,
    score_low: Annotated[float, Query(description="The lowest score the metric can give.")] = 0.0,
    score_high: Annotated[float, Query(description="The highest score the metric can give.")] = 1.0,
) -> ComparisonOut:
    """Paired bootstrap of candidate minus baseline, the same test as `signalfloor compare`.

    For more resamples than this endpoint allows, use POST /jobs/compare.
    """
    try:
        return await compare(
            session,
            baseline_id,
            candidate_id,
            confidence=confidence,
            n_resamples=n_resamples,
            seed=seed,
            shared_only=shared_only,
            margin=margin,
            score_range=(score_low, score_high),
        )
    except RunNotFound as e:
        raise HTTPException(404, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/{baseline_id}/diff/{candidate_id}")
async def diff_runs(
    baseline_id: uuid.UUID,
    candidate_id: uuid.UUID,
    session: Session,
    limit: Annotated[int, Query(ge=1, le=500)] = 20,
) -> RunDiffOut:
    """How many cases got worse or better, and the `limit` biggest drops and gains."""
    try:
        return await diff(session, baseline_id, candidate_id, limit=limit)
    except RunNotFound as e:
        raise HTTPException(404, str(e)) from e


async def _get(session: AsyncSession, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")
    return run


def _parse_labels(pairs: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise HTTPException(422, f"label filter must look like key=value, got {pair!r}")
        labels[key] = value
    return labels
