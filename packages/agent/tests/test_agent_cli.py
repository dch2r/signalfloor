import argparse
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from signalfloor_agent import cli
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
