import subprocess
from pathlib import Path

import httpx
import pytest

from signalfloor_agent import manifest
from signalfloor_agent.data import Passage


def test_manifest_sits_next_to_the_results() -> None:
    assert manifest.manifest_path(Path("runs/v1.jsonl")) == Path("runs/v1.manifest.json")


def test_corpus_hash_changes_with_any_passage() -> None:
    corpus = [Passage("Paris", "Capital of France."), Passage("Lyon", "A city.")]

    same = manifest.corpus_hash(list(corpus))
    edited = manifest.corpus_hash([corpus[0], Passage("Lyon", "A big city.")])

    assert manifest.corpus_hash(corpus) == same
    assert edited != same


def test_code_hash_covers_eval_code_but_not_test_helpers(tmp_path: Path) -> None:
    (tmp_path / "agent.py").write_text("x = 1\n")
    (tmp_path / "testing.py").write_text("fake = 1\n")
    before = manifest.code_hash(tmp_path)

    (tmp_path / "testing.py").write_text("fake = 2\n")
    assert manifest.code_hash(tmp_path) == before

    (tmp_path / "agent.py").write_text("x = 2\n")
    assert manifest.code_hash(tmp_path) != before


def test_git_commit_is_none_without_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def no_git(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", no_git)

    assert manifest.git_commit() is None


def test_git_commit_in_this_repository() -> None:
    commit = manifest.git_commit()

    assert commit is None or len(commit) == 40


def ollama(handler: object) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))  # type: ignore[arg-type]


def test_model_digest_from_ollama() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localhost:11434/api/tags"
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "nomic-embed-text:latest", "digest": "aaa"},
                    {"name": "qwen3:1.7b", "digest": "bbb"},
                ]
            },
        )

    digest = manifest.model_digest("qwen3:1.7b", "http://localhost:11434/v1", ollama(handler))

    assert digest == "bbb"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(404),
        httpx.Response(200, text="not json"),
        httpx.Response(200, json={"models": [{"name": "other", "digest": "x"}]}),
        httpx.Response(200, json={"models": [{"name": "qwen3:1.7b"}]}),
        httpx.Response(200, json=["not", "a", "dict"]),
    ],
)
def test_model_digest_is_none_when_the_server_cant_say(response: httpx.Response) -> None:
    client = ollama(lambda request: response)

    assert manifest.model_digest("qwen3:1.7b", "http://hosted.example/v1", client) is None


def test_model_digest_is_none_when_the_server_is_down() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    assert manifest.model_digest("m", "http://localhost:1/v1", ollama(refuse)) is None


def test_a_new_run_writes_the_manifest(tmp_path: Path) -> None:
    out = tmp_path / "runs" / "a.jsonl"

    manifest.check_or_write(out, {"prompt": "v1"}, {"git_commit": "abc"})

    saved = manifest_path_json(out)
    assert saved["identity"] == {"prompt": "v1"}
    assert saved["info"]["git_commit"] == "abc"
    assert "created_at" in saved["info"]


def test_an_empty_results_file_counts_as_new(tmp_path: Path) -> None:
    out = tmp_path / "a.jsonl"
    out.write_text("\n")

    manifest.check_or_write(out, {"prompt": "v2"})

    assert manifest_path_json(out)["identity"] == {"prompt": "v2"}


def test_a_new_setting_counts_as_a_change(tmp_path: Path) -> None:
    out = tmp_path / "a.jsonl"
    manifest.check_or_write(out, {"prompt": "v1"})
    out.write_text('{"id": "q0"}\n')

    with pytest.raises(manifest.ManifestMismatch, match="seed: None before, 3 now"):
        manifest.check_or_write(out, {"prompt": "v1", "seed": 3})


def manifest_path_json(out: Path) -> dict[str, dict[str, object]]:
    import json

    data: dict[str, dict[str, object]] = json.loads(manifest.manifest_path(out).read_text())
    return data
