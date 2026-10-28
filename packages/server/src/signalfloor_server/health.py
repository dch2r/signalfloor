"""Liveness and readiness checks.

Live means the process answers. Ready means it can also reach the database. Kubernetes restarts
a pod that is not live and stops sending traffic to one that is not ready, so a database outage
takes pods out of rotation without restarting them all.
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
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
    except (OSError, SQLAlchemyError):
        response.status_code = 503
        return {"status": "unavailable", "database": "unreachable"}
    return {"status": "ok", "database": "ok"}
