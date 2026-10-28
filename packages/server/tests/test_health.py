import asyncio
from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from signalfloor_server.app import create_app
from signalfloor_server.config import Settings
from signalfloor_server.migrate import downgrade, head_revision, upgrade


def test_live(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_the_database_is_up(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "schema": head_revision()}


def test_not_ready_when_the_database_is_down() -> None:
    # Nothing listens on port 1, so the connection is refused straight away.
    app = create_app(Settings(database_url="postgresql+asyncpg://localhost:1/nothing"))

    with TestClient(app) as client:
        live = client.get("/health/live")
        ready = client.get("/health/ready")

    assert live.status_code == 200
    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "database": "unreachable"}


def test_settings_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALFLOOR_DATABASE_URL", "postgresql+asyncpg://db/x")

    assert Settings().database_url == "postgresql+asyncpg://db/x"


def test_openapi_reports_the_package_version(client: TestClient) -> None:
    assert client.get("/openapi.json").json()["info"]["version"] == version("signalfloor-server")


@pytest.mark.parametrize(("revision", "at"), [("0003", "0003"), ("base", "nothing")])
def test_not_ready_until_the_schema_is_migrated(database_url: str, revision: str, at: str) -> None:
    downgrade(database_url, revision)
    try:
        with TestClient(create_app(Settings(database_url=database_url))) as client:
            response = client.get("/health/ready")
    finally:
        upgrade(database_url)

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "database": "ok",
        "schema": f"at {at}, needs {head_revision()}",
    }


def test_not_ready_on_a_brand_new_database(database_url: str) -> None:
    # A database that was never migrated has no alembic_version table at all.
    async def drop_everything() -> None:
        engine = create_async_engine(database_url)
        async with engine.begin() as conn:
            await conn.execute(text("drop table alembic_version"))
        await engine.dispose()

    downgrade(database_url, "base")
    asyncio.run(drop_everything())
    try:
        with TestClient(create_app(Settings(database_url=database_url))) as client:
            response = client.get("/health/ready")
    finally:
        upgrade(database_url)

    assert response.status_code == 503
    assert response.json()["schema"] == f"at nothing, needs {head_revision()}"
