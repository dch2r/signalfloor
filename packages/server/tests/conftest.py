import asyncio
import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

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
            await conn.execute(text("truncate runs cascade"))
        await engine.dispose()

    asyncio.run(go())


@pytest.fixture
def client(database_url: str) -> Iterator[TestClient]:
    empty_tables(database_url)
    with TestClient(create_app(Settings(database_url=database_url))) as c:
        yield c
