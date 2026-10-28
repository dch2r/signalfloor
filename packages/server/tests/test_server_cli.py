import pytest
import uvicorn

from signalfloor_server import cli, migrate


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


def test_a_command_is_required() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])

    assert exit_info.value.code == 2
