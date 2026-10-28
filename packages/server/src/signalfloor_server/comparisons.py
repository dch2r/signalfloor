"""Compare two stored runs. Used by the HTTP endpoint and by background jobs."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from signalfloor.compare import paired_bootstrap
from signalfloor_server.models import CaseResult, Run
from signalfloor_server.schemas import ComparisonOut


class RunNotFound(LookupError):
    def __init__(self, run_id: uuid.UUID) -> None:
        super().__init__(f"run {run_id} not found")


async def compare(
    session: AsyncSession,
    baseline_id: uuid.UUID,
    candidate_id: uuid.UUID,
    *,
    confidence: float,
    n_resamples: int,
    seed: int | None,
) -> ComparisonOut:
    """Paired bootstrap of candidate minus baseline.

    Raises RunNotFound if a run doesn't exist and ValueError if the runs can't be paired.
    """
    baseline = await scores(session, baseline_id)
    candidate = await scores(session, candidate_id)
    # The bootstrap is CPU bound. Run it in a thread so the event loop stays free.
    result = await run_in_threadpool(
        paired_bootstrap,
        baseline,
        candidate,
        confidence=confidence,
        n_resamples=n_resamples,
        seed=seed,
    )
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


async def scores(session: AsyncSession, run_id: uuid.UUID) -> dict[str, float]:
    if await session.get(Run, run_id) is None:
        raise RunNotFound(run_id)
    rows = await session.execute(
        select(CaseResult.case_id, CaseResult.score).where(CaseResult.run_id == run_id)
    )
    return {case_id: score for case_id, score in rows}
