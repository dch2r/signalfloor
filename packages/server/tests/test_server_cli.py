import json

import pytest
import uvicorn

from signalfloor_server import cli, jobs, migrate, retention


def test_migrate(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[str] = []
    monkeypatch.setenv("SIGNALFLOOR_DATABASE_URL", "postgresql+asyncpg://db/x")
    monkeypatch.setattr(migrate, "upgrade", seen.append)

    assert cli.main(["migrate"]) == 0
    assert seen == ["postgresql+asyncpg://db/x"]
    assert "database schema is up to date" in capsys.readouterr().out


def test_serve(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, object] = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: seen.update(kwargs))

    assert cli.main(["serve", "--port", "9000"]) == 0
    assert seen == {"host": "127.0.0.1", "port": 9000}


def test_serve_with_several_processes(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[object] = []
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: seen.extend([app, kwargs]))

    assert cli.main(["serve", "--workers", "4"]) == 0
    assert seen == [
        "signalfloor_server.app:create_app",
        {"factory": True, "workers": 4, "host": "127.0.0.1", "port": 8000},
    ]


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 2


def test_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[float] = []

    async def fake_work(sessions: object, stop: object, *, poll_interval: float) -> None:
        seen.append(poll_interval)

    monkeypatch.setattr(jobs, "work", fake_work)

    assert cli.main(["worker", "--poll-interval", "0.5"]) == 0
    assert seen == [0.5]


def test_prune_spans(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    async def fake_prune(session: object, older_than: object) -> int:
        return 3

    monkeypatch.setattr(retention, "prune_spans", fake_prune)

    assert cli.main(["prune-spans"]) == 0
    assert "deleted 3 spans older than 30 days" in capsys.readouterr().out


def test_openapi(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["openapi"]) == 0

    schema = json.loads(capsys.readouterr().out)
    assert schema["info"]["title"] == "signalfloor"
    assert "/runs/{baseline_id}/compare/{candidate_id}" in schema["paths"]


def test_importing_main_does_not_start_anything() -> None:
    # Server worker processes re-import the module that launched them. If importing it ran the
    # CLI, every worker would start a whole new server.
    import importlib

    importlib.import_module("signalfloor_server.__main__")


def test_the_command_points_at_the_cli() -> None:
    from importlib.metadata import entry_points

    (command,) = entry_points(group="console_scripts", name="signalfloor-server")
    assert command.value == "signalfloor_server.cli:main"
