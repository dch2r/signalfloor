from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from signalfloor_server import health, job_routes, runs, traces
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
    app.add_exception_handler(RequestValidationError, validation_error)
    app.include_router(health.router)
    app.include_router(runs.router)
    app.include_router(traces.router)
    app.include_router(job_routes.router)
    return app
