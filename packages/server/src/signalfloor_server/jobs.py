"""A job queue in Postgres, and the worker that runs it.

Workers claim jobs with SELECT ... FOR UPDATE SKIP LOCKED, so several workers can share one
queue without ever taking the same job, and without a separate broker such as Redis.

A claim is a lease. If a worker dies mid job, the lease runs out and another worker claims the
job again. Each claim adds one to attempts, and a worker only records its outcome if attempts
still matches its own claim. A worker that was too slow and lost its lease can't overwrite the
result of the worker that took over.

A job that raises is retried with exponential backoff up to max_attempts. A job that can never
succeed, such as a comparison of a deleted run, fails straight away.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import traceback
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from signalfloor_server.comparisons import RunNotFound, compare
from signalfloor_server.models import Job

log = logging.getLogger(__name__)

LEASE = timedelta(minutes=10)
BACKOFF_SECONDS = 2.0
MAX_RETRY_SECONDS = 30.0


class PermanentError(Exception):
    """The job can't succeed however often it is retried."""


Handler = Callable[[AsyncSession, dict[str, Any]], Awaitable[dict[str, Any]]]


async def _compare(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        result = await compare(
            session,
            uuid.UUID(payload["baseline_id"]),
            uuid.UUID(payload["candidate_id"]),
            confidence=payload["confidence"],
            n_resamples=payload["n_resamples"],
            seed=payload["seed"],
            # Jobs queued before this option existed don't have it.
            shared_only=payload.get("shared_only", False),
            margin=payload.get("margin"),
            score_range=(payload.get("score_low", 0.0), payload.get("score_high", 1.0)),
        )
    except (RunNotFound, ValueError) as e:
        raise PermanentError(str(e)) from e
    return result.model_dump(mode="json")


HANDLERS: dict[str, Handler] = {"compare": _compare}


async def enqueue(
    session: AsyncSession, kind: str, payload: dict[str, Any], *, max_attempts: int = 3
) -> Job:
    if kind not in HANDLERS:
        raise ValueError(f"unknown job kind {kind!r}")
    job = Job(kind=kind, payload=payload, max_attempts=max_attempts)
    session.add(job)
    await session.flush()
    return job


@dataclass(frozen=True)
class Claim:
    id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int


async def claim(session: AsyncSession, lease: timedelta = LEASE) -> Claim | None:
    """Take the next due job, or a running job whose lease ran out. None if there is none."""
    next_job = (
        select(Job.id)
        .where(Job.status.in_(("queued", "running")), Job.run_after <= func.now())
        .order_by(Job.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    row = (
        await session.execute(
            update(Job)
            .where(Job.id == next_job)
            .values(
                status="running",
                attempts=Job.attempts + 1,
                started_at=func.now(),
                run_after=func.now() + lease,
            )
            .returning(Job.id, Job.kind, Job.payload, Job.attempts, Job.max_attempts)
            .execution_options(synchronize_session=False)
        )
    ).one_or_none()
    await session.commit()
    return Claim(*row) if row else None


async def run_one(sessions: async_sessionmaker[AsyncSession], lease: timedelta = LEASE) -> bool:
    """Claim and run one job. Returns False if there was nothing to do."""
    async with sessions() as session:
        job = await claim(session, lease)
    if job is None:
        return False

    log.info("running %s job %s, attempt %d", job.kind, job.id, job.attempts)
    if job.attempts > job.max_attempts:
        # Its workers kept dying before they could record anything.
        await _finish(sessions, job, "failed", error=f"gave up after {job.max_attempts} attempts")
        return True
    handler = HANDLERS.get(job.kind)
    if handler is None:
        await _finish(sessions, job, "failed", error=f"unknown job kind {job.kind!r}")
        return True

    try:
        async with sessions() as session:
            result = await handler(session, job.payload)
    except PermanentError as e:
        await _finish(sessions, job, "failed", error=str(e))
    except Exception:
        error = traceback.format_exc()
        log.exception("%s job %s failed on attempt %d", job.kind, job.id, job.attempts)
        if job.attempts < job.max_attempts:
            delay = timedelta(seconds=BACKOFF_SECONDS * 2 ** (job.attempts - 1))
            await _finish(sessions, job, "queued", error=error, retry_in=delay)
        else:
            await _finish(sessions, job, "failed", error=error)
    else:
        await _finish(sessions, job, "succeeded", result=result)
    return True


async def _finish(
    sessions: async_sessionmaker[AsyncSession],
    job: Claim,
    status: str,
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    retry_in: timedelta | None = None,
) -> None:
    values: dict[str, Any] = {"status": status, "result": result, "error": error}
    if retry_in is None:
        values["finished_at"] = func.now()
    else:
        values["run_after"] = func.now() + retry_in
    async with sessions() as session:
        updated = await session.execute(
            update(Job)
            # Only if this is still our claim. See the module docstring.
            .where(Job.id == job.id, Job.attempts == job.attempts, Job.status == "running")
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    if updated.rowcount == 0:  # type: ignore[attr-defined]
        log.warning("lost the lease on %s job %s, result dropped", job.kind, job.id)


async def work(
    sessions: async_sessionmaker[AsyncSession],
    stop: asyncio.Event,
    *,
    poll_interval: float = 1.0,
    lease: timedelta = LEASE,
) -> None:
    """Run jobs until stop is set. A job in progress is finished first.

    If the database can't be reached, or isn't migrated yet, the worker waits and tries again
    instead of crashing. On a fresh Kubernetes install the worker starts before the migration
    job has created the tables, and crashing there only gets it restarted in a loop.
    """
    failures = 0
    while not stop.is_set():
        try:
            worked = await run_one(sessions, lease)
            failures = 0
        except (OSError, SQLAlchemyError) as e:
            failures += 1
            log.warning("database not available (%s), retrying", type(e).__name__)
            worked = False
        if not worked:
            # Back off while the database is down, up to half a minute between tries.
            delay = min(poll_interval * 2**failures, MAX_RETRY_SECONDS)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), delay)
