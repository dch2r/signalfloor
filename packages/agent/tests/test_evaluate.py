import json
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from signalfloor_agent.agent import Agent, AgentConfig
from signalfloor_agent.data import Passage, Question
from signalfloor_agent.evaluate import read_results, run_eval, summarize
from signalfloor_agent.retrieval import KeywordRetriever
from signalfloor_agent.testing import ScriptedChatModel, tool_call

CORPUS = (
    Passage("Doctor Strange", "Doctor Strange is a 2016 film directed by Scott Derrickson."),
    Passage("Scott Derrickson", "Scott Derrickson is an American director."),
    Passage("Paris", "Paris is the capital of France."),
)

QUESTIONS = (
    Question(
        "q1",
        "Nationality of the Doctor Strange director?",
        "American",
        "bridge",
        "hard",
        ("Doctor Strange", "Scott Derrickson"),
        (),
    ),
    Question("q2", "Capital of France?", "Paris", "bridge", "hard", ("Paris", "France"), ()),
)


def make_agent(*replies: AIMessage) -> Agent:
    model = ScriptedChatModel(replies=list(replies))
    return Agent(model, KeywordRetriever(CORPUS), AgentConfig(passages_per_search=1))


def test_writes_one_scored_line_per_question(tmp_path: Path) -> None:
    agent = make_agent(
        tool_call("Doctor Strange director", "a"),
        tool_call("Scott Derrickson", "b"),
        AIMessage("American"),
        AIMessage("Lyon"),
    )
    out = tmp_path / "runs" / "v1.jsonl"
    lines: list[str] = []

    results = run_eval(agent, QUESTIONS, out, progress=lines.append)

    assert [r.id for r in results] == ["q1", "q2"]
    first, second = results
    assert (first.score, first.exact_match, first.searches) == (1.0, 1.0, 2)
    assert first.supporting_recall == 1.0
    assert (second.score, second.answer, second.supporting_recall) == (0.0, "Lyon", 0.0)

    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert [row["id"] for row in rows] == ["q1", "q2"]
    assert set(rows[0]) == {
        "id",
        "score",
        "exact_match",
        "answer",
        "searches",
        "supporting_recall",
        "hit_search_limit",
        "seconds",
        "trace_id",
    }
    assert "American" not in json.dumps(rows[0]["id"]), "no gold text beyond our own answer"
    assert lines[0].startswith("[1/2] f1 1.00 searches 2")


def test_resumes_where_it_stopped(tmp_path: Path) -> None:
    out = tmp_path / "run.jsonl"
    run_eval(make_agent(AIMessage("American")), QUESTIONS[:1], out)

    # Only one reply is scripted, so the model would fail if q1 were asked again.
    results = run_eval(make_agent(AIMessage("Paris")), QUESTIONS, out)

    assert [r.answer for r in results] == ["American", "Paris"]
    assert [r.id for r in read_results(out)] == ["q1", "q2"]


def test_summarize(tmp_path: Path) -> None:
    out = tmp_path / "run.jsonl"
    results = run_eval(make_agent(AIMessage("American"), AIMessage("Lyon")), QUESTIONS, out)

    s = summarize(results)

    assert s.cases == 2
    assert s.mean_f1 == 0.5
    assert s.mean_exact_match == 0.5
    assert s.mean_searches == 0
    assert s.hit_search_limit == 0


def test_summarize_needs_results() -> None:
    with pytest.raises(ValueError, match="no results"):
        summarize([])


def test_signalfloor_can_read_the_output(tmp_path: Path) -> None:
    from signalfloor.results import load_scores

    out = tmp_path / "run.jsonl"
    run_eval(make_agent(AIMessage("American"), AIMessage("Paris")), QUESTIONS, out)

    assert load_scores(out) == {"q1": 1.0, "q2": 1.0}
