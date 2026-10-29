"""Compare two stored runs. Used by the HTTP endpoint and by background jobs.

The bootstrap is the most expensive thing the server does. A load test showed comparisons
using up every core and starving cheap requests like listing runs, so two things keep it in
check:

- Results with a fixed seed are cached. Runs never change after upload, so the same runs,
  options and seed always give the same answer. The dashboard always uses seed 0.
- At most one fewer bootstrap than there are cores runs at a time, leaving a core for the rest
  of the server. Others wait their turn.
"""

from __future__ import annotations

import os
import uuid
from collections import OrderedDict
from functools import partial

import anyio
from sqlalchemy import Select, and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from signalfloor.compare import paired_bootstrap
from signalfloor_server.models import CaseResult, Run
from signalfloor_server.schemas import CaseDiff, ComparisonOut, RunDiffOut

CACHE_SIZE = 1024
_cache: OrderedDict[tuple[object, ...], ComparisonOut] = OrderedDict()
_bootstraps = anyio.CapacityLimiter(max(1, (os.cpu_count() or 2) - 1))


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
    shared_only: bool = False,
    margin: float | None = None,
) -> ComparisonOut:
    """Paired bootstrap of candidate minus baseline.

    By default both runs must have exactly the same cases, like `signalfloor compare`. With
    shared_only, cases in only one run are left out and the rest are compared. The caller is
    then responsible for telling the user how many were left out.

    Raises RunNotFound if a run doesn't exist and ValueError if the runs can't be paired.
    """
    # Check the runs exist every time, so a run deleted after it was cached is still a 404.
    for run_id in (baseline_id, candidate_id):
        if await session.get(Run, run_id) is None:
            raise RunNotFound(run_id)
    key = (baseline_id, candidate_id, confidence, n_resamples, seed, shared_only, margin)
    if seed is not None and key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    baseline = await scores(session, baseline_id)
    candidate = await scores(session, candidate_id)
    if shared_only:
        shared = baseline.keys() & candidate.keys()
        baseline = {k: v for k, v in baseline.items() if k in shared}
        candidate = {k: v for k, v in candidate.items() if k in shared}
    # CPU bound, so it runs in a thread to keep the event loop free, and through the limiter.
    result = await anyio.to_thread.run_sync(
        partial(
            paired_bootstrap,
            baseline,
            candidate,
            confidence=confidence,
            n_resamples=n_resamples,
            seed=seed,
            margin=margin,
        ),
        limiter=_bootstraps,
    )
    comparison = ComparisonOut(
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
        largest_drop_not_ruled_out=result.largest_drop_not_ruled_out,
        margin=result.margin,
        decision=result.decision.value if result.decision else None,
    )
    if seed is not None:
        _cache[key] = comparison
        if len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return comparison


async def scores(session: AsyncSession, run_id: uuid.UUID) -> dict[str, float]:
    """Every case's score in a run. The caller checks that the run exists."""
    rows = await session.execute(
        select(CaseResult.case_id, CaseResult.score).where(CaseResult.run_id == run_id)
    )
    return {case_id: score for case_id, score in rows}


async def diff(
    session: AsyncSession, baseline_id: uuid.UUID, candidate_id: uuid.UUID, *, limit: int
) -> RunDiffOut:
    """Case by case changes between two runs: counts, and the biggest drops and gains.

    Only cases in both runs are paired. Cases in just one run are counted, not compared.
    """
    runs = {}
    for run_id in (baseline_id, candidate_id):
        run = await session.get(Run, run_id)
        if run is None:
            raise RunNotFound(run_id)
        runs[run_id] = run

    base = aliased(CaseResult)
    cand = aliased(CaseResult)
    delta = (cand.score - base.score).label("delta")
    paired = (
        select(
            base.case_id,
            base.score,
            cand.score,
            delta,
            base.trace_id,
            cand.trace_id,
        )
        .join(cand, and_(cand.case_id == base.case_id, cand.run_id == candidate_id))
        .where(base.run_id == baseline_id)
    )

    shared = paired.subquery()
    counts = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(shared.c.delta < 0),
                func.count().filter(shared.c.delta > 0),
            )
        )
    ).one()
    n_shared, n_worse, n_better = counts

    async def cases(
        query: Select[str, float, float, float, str | None, str | None],
    ) -> list[CaseDiff]:
        rows = await session.execute(query.limit(limit))
        return [
            CaseDiff(
                case_id=case_id,
                baseline_score=b,
                candidate_score=c,
                delta=d,
                baseline_trace_id=bt,
                candidate_trace_id=ct,
            )
            for case_id, b, c, d, bt, ct in rows
        ]

    return RunDiffOut(
        baseline_id=baseline_id,
        candidate_id=candidate_id,
        n_shared=n_shared,
        n_worse=n_worse,
        n_better=n_better,
        n_same=n_shared - n_worse - n_better,
        only_in_baseline=runs[baseline_id].n_cases - n_shared,
        only_in_candidate=runs[candidate_id].n_cases - n_shared,
        worst=await cases(paired.where(delta < 0).order_by(delta, base.case_id)),
        best=await cases(paired.where(delta > 0).order_by(delta.desc(), base.case_id)),
    )
