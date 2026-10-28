"""Upload, list, fetch, delete and compare eval runs."""

from __future__ import annotations

import math
import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from signalfloor.compare import paired_bootstrap
from signalfloor_server.models import CaseResult, Run
from signalfloor_server.schemas import ComparisonOut, RunIn, RunOut

MAX_RESAMPLES = 100_000

router = APIRouter(prefix="/runs", tags=["runs"])


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    async with request.app.state.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


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
        [{"run_id": run.id, "case_id": c.id, "score": c.score} for c in body.cases],
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
) -> ComparisonOut:
    """Paired bootstrap of candidate minus baseline, the same test as `signalfloor compare`."""
    baseline = await _scores(session, baseline_id)
    candidate = await _scores(session, candidate_id)
    try:
        # The bootstrap is CPU bound. Run it in a thread so other requests keep being served.
        result = await run_in_threadpool(
            paired_bootstrap,
            baseline,
            candidate,
            confidence=confidence,
            n_resamples=n_resamples,
            seed=seed,
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return ComparisonOut(
        baseline_id=baseline_id,
        candidate_id=candidate_id,
        baseline_mean=result.baseline_mean,
        candidate_mean=result.candidate_mean,
        delta=result.delta,
        ci_low=result.ci_low,
        ci_high=result.ci_high,
        confidence=result.confidence,
        n_cases=result.n_cases,
        n_resamples=result.n_resamples,
        verdict=result.verdict.value,
    )


async def _get(session: AsyncSession, run_id: uuid.UUID) -> Run:
    run = await session.get(Run, run_id)
    if run is None:
        raise HTTPException(404, f"run {run_id} not found")
    return run


async def _scores(session: AsyncSession, run_id: uuid.UUID) -> dict[str, float]:
    await _get(session, run_id)
    rows = await session.execute(
        select(CaseResult.case_id, CaseResult.score).where(CaseResult.run_id == run_id)
    )
    return {case_id: score for case_id, score in rows}


def _parse_labels(pairs: list[str]) -> dict[str, str]:
    labels: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise HTTPException(422, f"label filter must look like key=value, got {pair!r}")
        labels[key] = value
    return labels
