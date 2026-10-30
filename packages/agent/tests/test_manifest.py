import dataclasses
import subprocess
from pathlib import Path
from typing import Any

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


def manifest_path_json(out: Path) -> dict[str, Any]:
    import json

    data: dict[str, Any] = json.loads(manifest.manifest_path(out).read_text())
    return data


FINGERPRINTS = [["q0", "aaaa"], ["q1", "bbbb"], ["q2", "cccc"]]


def started(tmp_path: Path, identity: dict[str, object], questions: list[list[str]]) -> Path:
    out = tmp_path / "a.jsonl"
    manifest.check_or_write(out, identity, questions=questions)
    out.write_text('{"id": "q0"}\n')
    return out


def test_a_run_can_grow_or_shrink_but_not_change_its_questions(tmp_path: Path) -> None:
    out = started(tmp_path, {"prompt": "v1"}, FINGERPRINTS[:2])

    manifest.check_or_write(out, {"prompt": "v1"}, questions=FINGERPRINTS)
    assert manifest_path_json(out)["questions"] == FINGERPRINTS
    manifest.check_or_write(out, {"prompt": "v1"}, questions=FINGERPRINTS[:1])
    assert manifest_path_json(out)["questions"] == FINGERPRINTS

    edited = [["q0", "aaaa"], ["q1", "zzzz"]]
    with pytest.raises(manifest.ManifestMismatch, match="Question 2 was 'q1' and is now the same"):
        manifest.check_or_write(out, {"prompt": "v1"}, questions=edited)
    other = [["q0", "aaaa"], ["q9", "bbbb"]]
    with pytest.raises(manifest.ManifestMismatch, match="now a different question"):
        manifest.check_or_write(out, {"prompt": "v1"}, questions=other)


def test_a_digest_is_checked_once_it_is_known(tmp_path: Path) -> None:
    out = started(tmp_path, {"model_digest": "sha256:a"}, [])

    manifest.check_or_write(out, {"model_digest": "sha256:a"})
    with pytest.raises(manifest.ManifestMismatch, match="model_digest"):
        manifest.check_or_write(out, {"model_digest": "sha256:b"})
    # A digest that is now unknown can't be shown to match.
    with pytest.raises(manifest.ManifestMismatch, match="model_digest"):
        manifest.check_or_write(out, {"model_digest": None})


def test_a_server_that_never_reports_a_digest_is_not_blocked(tmp_path: Path) -> None:
    out = started(tmp_path, {"model_digest": None}, [])

    manifest.check_or_write(out, {"model_digest": None})


def test_a_digest_that_was_unknown_at_the_start_never_counts_as_verified(tmp_path: Path) -> None:
    # If unknown counted as matching anything, a run could start unknown, resume with A and
    # then with B, so one failed lookup would leave it unchecked for good.
    out = started(tmp_path, {"model_digest": None}, [])

    with pytest.raises(manifest.ManifestMismatch, match="model_digest: None before, 'sha256:a'"):
        manifest.check_or_write(out, {"model_digest": "sha256:a"})


@pytest.mark.parametrize(
    ("requested", "listed"),
    [
        ("nomic-embed-text", "nomic-embed-text:latest"),
        ("nomic-embed-text:latest", "nomic-embed-text"),
        ("qwen3:1.7b", "qwen3:1.7b"),
        ("hf.co/org/model", "hf.co/org/model:latest"),
    ],
)
def test_untagged_names_find_the_latest_tag(requested: str, listed: str) -> None:
    # The default embedding model has no tag and Ollama lists it with one. An exact match
    # never finds its digest, so it would never be checked.
    entry = {"name": listed, "model": listed, "digest": "sha256:e"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [entry]}))

    digest = manifest.model_digest(requested, "http://x/v1", httpx.Client(transport=transport))

    assert digest == "sha256:e"


def test_a_different_tag_is_a_different_model() -> None:
    entry = {"name": "qwen3:8b", "digest": "sha256:big"}
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": [entry]}))

    assert manifest.model_digest("qwen3", "http://x/v1", httpx.Client(transport=transport)) is None


def test_manifests_from_before_question_checks_are_refused(tmp_path: Path) -> None:
    import json

    out = started(tmp_path, {"prompt": "v1"}, [])
    path = manifest.manifest_path(out)
    old = json.loads(path.read_text())
    old["manifest_version"] = 1
    path.write_text(json.dumps(old))

    with pytest.raises(manifest.ManifestMismatch, match="older signalfloor-agent"):
        manifest.check_or_write(out, {"prompt": "v1"})


def test_question_fingerprints_cover_text_answer_and_supporting_facts() -> None:
    from signalfloor_agent.data import Question

    base = Question("q0", "Who?", "Paris", "bridge", "hard", ("A", "B"), ())
    changes = [
        dataclasses.replace(base, question="Who else?"),
        dataclasses.replace(base, answer="Lyon"),
        dataclasses.replace(base, supporting_titles=("A", "C")),
    ]

    [[_, original]] = manifest.question_fingerprints([base])
    for changed in changes:
        assert manifest.question_fingerprints([changed])[0][1] != original
    # Fields the score doesn't use don't count.
    assert manifest.question_fingerprints([dataclasses.replace(base, level="easy")]) == [
        ["q0", original]
    ]


def test_entries_that_are_not_objects_are_skipped() -> None:
    models = ["junk", {"name": "qwen3:1.7b", "digest": "sha256:q"}]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"models": models}))

    assert manifest.model_digest(
        "qwen3:1.7b", "http://x/v1", httpx.Client(transport=transport)
    ) == ("sha256:q")
