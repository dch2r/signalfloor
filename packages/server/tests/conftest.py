import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from signalfloor_server import comparisons
from signalfloor_server.app import create_app
from signalfloor_server.config import Settings
from signalfloor_server.migrate import downgrade, upgrade

# A separate database, because the tests drop and recreate every table.
TEST_DATABASE_URL = os.environ.get(
    "SIGNALFLOOR_TEST_DATABASE_URL", "postgresql+asyncpg://localhost/signalfloor_test"
)


@pytest.fixture(scope="session")
def database_url() -> str:
    downgrade(TEST_DATABASE_URL, "base")
    upgrade(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


def empty_tables(database_url: str) -> None:
    async def go() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as conn:
            await conn.execute(text("truncate runs, spans, jobs cascade"))
        await engine.dispose()

    asyncio.run(go())


@pytest.fixture
def clean_db(database_url: str) -> str:
    empty_tables(database_url)
    comparisons._cache.clear()
    return database_url


@pytest.fixture
def client(clean_db: str) -> Iterator[TestClient]:
    database_url = clean_db
    with TestClient(create_app(Settings(database_url=database_url))) as c:
        yield c
