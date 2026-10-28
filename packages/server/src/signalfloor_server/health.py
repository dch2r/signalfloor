"""Liveness and readiness checks.

Live means the process answers. Ready means it can reach the database and the schema is at the
migration this code was written for. Kubernetes restarts a pod that is not live and stops
sending traffic to one that is not ready:

- A database outage takes pods out of rotation without restarting them all.
- On a fresh install, or after an upgrade with a new migration, pods wait for the migration job
  instead of serving requests against tables that don't exist yet.
"""

from fastapi import APIRouter, Request, Response
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def live() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def ready(request: Request, response: Response) -> dict[str, str]:
    engine: AsyncEngine = request.app.state.engine
    expected: str = request.app.state.schema_revision
    try:
        async with engine.connect() as conn:
            # to_regclass is null when the table doesn't exist, which is the case before the
            # first migration. Selecting from a missing table would raise instead.
            exists = await conn.scalar(text("select to_regclass('alembic_version')"))
            current = (
                await conn.scalar(text("select version_num from alembic_version"))
                if exists
                else None
            )
    except (OSError, SQLAlchemyError):
        response.status_code = 503
        return {"status": "unavailable", "database": "unreachable"}

    if current != expected:
        response.status_code = 503
        return {
            "status": "unavailable",
            "database": "ok",
            "schema": f"at {current or 'nothing'}, needs {expected}",
        }
    return {"status": "ok", "database": "ok", "schema": current}
