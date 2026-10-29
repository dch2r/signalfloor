from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from signalfloor_server.app import create_app
from signalfloor_server.config import Settings


@pytest.fixture
def locked(clean_db: str) -> Iterator[TestClient]:
    settings = Settings(database_url=clean_db, api_keys="old-key, new-key")
    with TestClient(create_app(settings)) as client:
        yield client


def bearer(key: str) -> dict[str, str]:
    return {"authorization": f"Bearer {key}"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/runs"),
        ("POST", "/runs"),
        ("DELETE", "/runs/00000000-0000-0000-0000-000000000000"),
        ("POST", "/v1/traces"),
        ("GET", "/traces/" + "0" * 32),
        ("POST", "/jobs/compare"),
    ],
)
def test_every_data_endpoint_needs_a_key(locked: TestClient, method: str, path: str) -> None:
    response = locked.request(method, path)

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json() == {"detail": "missing or wrong API key"}


@pytest.mark.parametrize(
    "headers",
    [
        {"authorization": "Bearer wrong"},
        {"authorization": "old-key"},
        {"authorization": "Basic old-key"},
        {"x-api-key": "old-key"},
    ],
)
def test_wrong_or_badly_sent_keys_are_refused(locked: TestClient, headers: dict[str, str]) -> None:
    assert locked.get("/runs", headers=headers).status_code == 401


@pytest.mark.parametrize("key", ["old-key", "new-key"])
def test_any_configured_key_works_so_keys_can_be_rotated(locked: TestClient, key: str) -> None:
    assert locked.get("/runs", headers=bearer(key)).status_code == 200


def test_the_scheme_is_case_insensitive(locked: TestClient) -> None:
    assert locked.get("/runs", headers={"authorization": "bearer old-key"}).status_code == 200


def test_health_checks_stay_open_for_probes(locked: TestClient) -> None:
    assert locked.get("/health/live").status_code == 200
    assert locked.get("/health/ready").status_code == 200


def test_without_keys_the_api_is_open_and_says_so(
    clean_db: str, caplog: pytest.LogCaptureFixture
) -> None:
    with TestClient(create_app(Settings(database_url=clean_db))) as client:
        assert client.get("/runs").status_code == 200

    assert "SIGNALFLOOR_API_KEYS is not set" in caplog.text


def test_keys_are_read_from_a_comma_separated_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SIGNALFLOOR_API_KEYS", " a , b,, ")

    assert Settings().keys == ("a", "b")
