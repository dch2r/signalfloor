import argparse
import json
from pathlib import Path

import httpx
import httpx2
import openai
import pytest
from langchain_core.messages import AIMessage

from signalfloor_agent import cli, manifest, tracing
from signalfloor_agent.agent import SYSTEM_PROMPT_V2, Agent, AgentConfig
from signalfloor_agent.data import Dataset, Passage, Question, build_corpus
from signalfloor_agent.retrieval import DenseRetriever, HybridRetriever, KeywordRetriever
from signalfloor_agent.testing import HashingEmbedder, ScriptedChatModel

PASSAGES = (Passage("Paris", "Paris is the capital of France."), Passage("Lyon", "Lyon is big."))
QUESTIONS = tuple(
    Question(f"q{i}", "Capital of France?", "Paris", "bridge", "hard", ("Paris",), PASSAGES)
    for i in range(3)
)
DATASET = Dataset(QUESTIONS, build_corpus(QUESTIONS))


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    """Replace the dataset, model and embedder so the CLI runs with no network."""
    seen: dict[str, object] = {}

    def fake_load(n: int, *, offset: int = 0) -> Dataset:
        seen["load"] = (n, offset)
        return DATASET

    def fake_build_agent(args: argparse.Namespace, dataset: Dataset) -> Agent:
        seen["args"] = args
        model = ScriptedChatModel(replies=[AIMessage("Paris")] * 3)
        return Agent(model, KeywordRetriever(dataset.corpus), AgentConfig())

    monkeypatch.setattr(cli, "load_hotpot", fake_load)
    monkeypatch.setattr(cli, "build_agent", fake_build_agent)
    # No network or git in tests.
    monkeypatch.setattr(manifest, "model_digest", lambda model, base_url: "sha256:test")
    monkeypatch.setattr(manifest, "git_commit", lambda: "abc123")
    return seen


def test_eval_command(
    tmp_path: Path, offline: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "run.jsonl"

    code = cli.main(["eval", "--out", str(out), "--questions", "2", "--corpus-questions", "3"])

    output = capsys.readouterr().out
    assert code == 0
    assert offline["load"] == (3, 0)
    assert len(out.read_text().splitlines()) == 2
    assert "[2/2] f1 1.00" in output
    assert "cases 2  f1 1.000  exact match 1.000" in output


def test_quiet_hides_progress(
    tmp_path: Path, offline: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    cli.main(
        [
            "eval",
            "--out",
            str(tmp_path / "r.jsonl"),
            "--questions",
            "1",
            "--quiet",
            "--corpus-questions",
            "3",
        ]
    )

    assert "[1/1]" not in capsys.readouterr().out


def test_questions_cannot_exceed_corpus(
    tmp_path: Path, offline: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    code = cli.main(["eval", "--out", str(tmp_path / "r.jsonl"), "--questions", "300"])

    assert code == 2
    assert "--questions cannot be more than --corpus-questions" in capsys.readouterr().err


def args(**overrides: object) -> argparse.Namespace:
    defaults = dict(
        retriever="dense",
        embedding_model="nomic-embed-text",
        base_url="http://x/v1",
        max_searches=3,
        passages=2,
        prompt="v2",
        model="m",
    )
    return argparse.Namespace(**{**defaults, **overrides})


def test_build_agent_applies_options(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "build_retriever", lambda a, d: KeywordRetriever(d.corpus))

    agent = cli.build_agent(args(), DATASET)

    assert agent.config == AgentConfig(3, 2, SYSTEM_PROMPT_V2)


@pytest.mark.parametrize(
    ("retriever", "expected"),
    [("keyword", KeywordRetriever), ("dense", DenseRetriever), ("hybrid", HybridRetriever)],
)
def test_build_retriever(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, retriever: str, expected: type
) -> None:
    made: list[dict[str, object]] = []

    def fake_embedder(model: str, **kwargs: object) -> HashingEmbedder:
        made.append({"model": model, **kwargs})
        return HashingEmbedder()

    monkeypatch.setattr(cli, "OpenAICompatibleEmbedder", fake_embedder)
    monkeypatch.setattr(cli, "default_cache_dir", lambda: tmp_path)

    assert isinstance(cli.build_retriever(args(retriever=retriever), DATASET), expected)
    if retriever != "keyword":
        assert made[0]["document_prefix"] == "search_document: "


def test_prefixes_only_for_nomic_models(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    made: list[dict[str, object]] = []

    def fake_embedder(model: str, **kwargs: object) -> HashingEmbedder:
        made.append(kwargs)
        return HashingEmbedder()

    monkeypatch.setattr(cli, "OpenAICompatibleEmbedder", fake_embedder)
    monkeypatch.setattr(cli, "default_cache_dir", lambda: tmp_path)

    cli.build_retriever(args(embedding_model="all-minilm"), DATASET)

    assert made[0]["document_prefix"] == ""


def test_traces_are_flushed_at_the_end(
    tmp_path: Path, offline: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    class FakeProvider:
        def shutdown(self) -> None:
            calls.append("shutdown")

    def fake_configure(endpoint: str) -> FakeProvider:
        calls.append(endpoint)
        return FakeProvider()

    monkeypatch.setattr(tracing, "configure", fake_configure)

    cli.main(
        [
            "eval",
            "--out",
            str(tmp_path / "r.jsonl"),
            "--questions",
            "1",
            "--corpus-questions",
            "3",
            "--quiet",
            "--otlp-endpoint",
            "http://server/v1/traces",
        ]
    )

    assert calls == ["http://server/v1/traces", "shutdown"]


def eval_args(out: Path, *extra: str) -> list[str]:
    return [
        "eval",
        "--out",
        str(out),
        "--questions",
        "2",
        "--corpus-questions",
        "3",
        "--quiet",
        *extra,
    ]


def test_a_run_writes_its_manifest(tmp_path: Path, offline: dict[str, object]) -> None:
    out = tmp_path / "v1.jsonl"

    cli.main(eval_args(out))

    saved = json.loads((tmp_path / "v1.manifest.json").read_text())
    identity = saved["identity"]
    assert identity["prompt"] == "v1"
    assert identity["model"] == "qwen3:1.7b"
    assert identity["corpus_sha256"] == manifest.corpus_hash(DATASET.corpus)
    assert identity["code_sha256"] == manifest.code_hash()
    assert "questions" not in identity
    assert saved["info"]["git_commit"] == "abc123"
    assert saved["info"]["model_digest"] == "sha256:test"


def test_resuming_with_the_same_setup_works(tmp_path: Path, offline: dict[str, object]) -> None:
    out = tmp_path / "v1.jsonl"
    cli.main(eval_args(out))

    # Asking for one more question extends the same run.
    assert cli.main(eval_args(out, "--questions", "3")) == 0
    assert len(out.read_text().splitlines()) == 3


def test_resuming_with_another_prompt_is_refused(
    tmp_path: Path, offline: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "run.jsonl"
    cli.main(eval_args(out, "--prompt", "v1"))
    capsys.readouterr()

    code = cli.main(eval_args(out, "--prompt", "v2"))

    err = capsys.readouterr().err
    assert code == 2
    assert "was started with a different setup" in err
    assert "prompt: 'v1' before, 'v2' now" in err
    assert "prompt_sha256" in err
    assert len(out.read_text().splitlines()) == 2


def test_results_without_a_manifest_are_not_resumed(
    tmp_path: Path, offline: dict[str, object], capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "old.jsonl"
    out.write_text('{"id": "q0"}\n')

    assert cli.main(eval_args(out)) == 2
    assert "no manifest" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [
        httpx.ConnectError("refused"),
        # The openai SDK uses its own fork of httpx for requests.
        openai.APIConnectionError(request=httpx2.Request("POST", "http://localhost:11434/v1")),
    ],
)
def test_a_model_server_that_is_down_gives_one_clear_line(
    tmp_path: Path,
    offline: dict[str, object],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    error: Exception,
) -> None:
    def down(*args: object, **kwargs: object) -> None:
        raise error

    monkeypatch.setattr(cli, "run_eval", down)

    code = cli.main(eval_args(tmp_path / "r.jsonl"))

    err = capsys.readouterr().err
    assert code == 1
    assert "can't reach the model server at http://localhost:11434/v1. Is Ollama running?" in err
    assert "Traceback" not in err
