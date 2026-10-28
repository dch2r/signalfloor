"""Delete old spans so the spans table doesn't grow forever."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from signalfloor_server.models import Span

BATCH_SIZE = 10_000


async def prune_spans(
    session: AsyncSession, older_than: timedelta, *, batch_size: int = BATCH_SIZE
) -> int:
    """Delete spans that started more than older_than ago. Returns how many were deleted.

    Deletes in batches, each in its own transaction, so a large cleanup doesn't hold locks
    for long or build one huge transaction.
    """
    total = 0
    while True:
        batch = (
            select(Span.trace_id, Span.span_id)
            .where(Span.start_time < func.now() - older_than)
            .limit(batch_size)
        )
        result = await session.execute(
            delete(Span).where(tuple_(Span.trace_id, Span.span_id).in_(batch))
        )
        await session.commit()
        deleted: int = result.rowcount  # type: ignore[attr-defined]
        total += deleted
        if deleted < batch_size:
            return total
