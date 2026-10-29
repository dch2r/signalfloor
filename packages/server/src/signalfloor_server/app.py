import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import Depends, FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from signalfloor_server import health, job_routes, runs, traces
from signalfloor_server.auth import require_api_key
from signalfloor_server.config import Settings
from signalfloor_server.errors import validation_error
from signalfloor_server.migrate import head_revision

CONNECT_TIMEOUT_SECONDS = 5


def create_engine(settings: Settings) -> AsyncEngine:
    # Without a timeout a readiness check against an unreachable host hangs for minutes.
    return create_async_engine(
        settings.database_url,
        pool_pre_ping=True,
        connect_args={"timeout": CONNECT_TIMEOUT_SECONDS},
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = create_engine(settings)
        app.state.engine = engine
        app.state.sessions = async_sessionmaker(engine, expire_on_commit=False)
        yield
        await engine.dispose()

    app = FastAPI(title="signalfloor", version=version("signalfloor-server"), lifespan=lifespan)
    app.state.schema_revision = head_revision()
    app.state.api_keys = settings.keys
    if not settings.keys:
        logging.getLogger(__name__).warning(
            "SIGNALFLOOR_API_KEYS is not set, so the API is open to anyone who can reach it. "
            "That's fine on your own machine, not on a shared network."
        )
    app.add_exception_handler(RequestValidationError, validation_error)
    # Health checks stay open: Kubernetes probes them without credentials.
    app.include_router(health.router)
    protected = [Depends(require_api_key)]
    app.include_router(runs.router, dependencies=protected)
    app.include_router(traces.router, dependencies=protected)
    app.include_router(job_routes.router, dependencies=protected)
    return app
