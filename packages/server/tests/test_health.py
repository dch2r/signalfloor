from importlib.metadata import version

import pytest
from fastapi.testclient import TestClient

from signalfloor_server.app import create_app
from signalfloor_server.config import Settings


def test_live(client: TestClient) -> None:
    response = client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_when_the_database_is_up(client: TestClient) -> None:
    response = client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


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
