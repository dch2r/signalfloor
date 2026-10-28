import asyncio
from collections.abc import Callable
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from signalfloor_server.migrate import alembic_config, downgrade, upgrade
from signalfloor_server.models import Base


def with_connection(database_url: str, fn: Callable[[Connection], Any]) -> Any:
    async def go() -> Any:
        engine = create_async_engine(database_url)
        async with engine.connect() as conn:
            result = await conn.run_sync(fn)
        await engine.dispose()
        return result

    return asyncio.run(go())


def tables(conn: Connection) -> set[str]:
    return set(inspect(conn).get_table_names())


def test_migrations_go_down_and_up_again(database_url: str) -> None:
    downgrade(database_url, "base")
    assert with_connection(database_url, tables) == {"alembic_version"}

    upgrade(database_url)
    assert {"runs", "case_results"} <= with_connection(database_url, tables)


def test_models_match_the_migrations(database_url: str) -> None:
    # Catches a model change that was made without writing a migration for it.
    diff = with_connection(
        database_url, lambda conn: compare_metadata(MigrationContext.configure(conn), Base.metadata)
    )

    assert diff == []


def test_percent_signs_in_the_url_survive_the_config() -> None:
    url = "postgresql+asyncpg://user:p%40ss@db/x"

    assert alembic_config(url).get_main_option("sqlalchemy.url") == url
