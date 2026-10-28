from typing import Any

import pytest
from langchain_core.messages import AIMessage
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from signalfloor_agent import tracing
from signalfloor_agent.agent import Agent, AgentConfig
from signalfloor_agent.data import Passage, Question
from signalfloor_agent.evaluate import evaluate_case
from signalfloor_agent.retrieval import KeywordRetriever
from signalfloor_agent.testing import ScriptedChatModel, tool_call

CORPUS = (
    Passage("Doctor Strange", "Doctor Strange is a 2016 film directed by Scott Derrickson."),
    Passage("Scott Derrickson", "Scott Derrickson is an American director."),
)
QUESTION = Question(
    "q1", "Nationality?", "American", "bridge", "hard", ("Doctor Strange", "Scott Derrickson"), ()
)


def make_agent(*replies: AIMessage, max_searches: int = 4) -> Agent:
    model = ScriptedChatModel(replies=list(replies))
    config = AgentConfig(max_searches=max_searches, passages_per_search=1)
    return Agent(model, KeywordRetriever(CORPUS), config)


def by_name(spans: InMemorySpanExporter) -> dict[str, list[ReadableSpan]]:
    named: dict[str, list[ReadableSpan]] = {}
    for span in spans.get_finished_spans():
        named.setdefault(span.name, []).append(span)
    return named


def attrs(span: ReadableSpan) -> dict[str, Any]:
    return dict(span.attributes or {})


def test_one_trace_per_case_with_nested_spans(spans: InMemorySpanExporter) -> None:
    usage = {"input_tokens": 120, "output_tokens": 8, "total_tokens": 128}
    agent = make_agent(
        tool_call("Doctor Strange director", "c1"),
        tool_call("Scott Derrickson", "c2"),
        AIMessage("American", usage_metadata=usage),
    )

    case = evaluate_case(agent, QUESTION)

    named = by_name(spans)
    (root,) = named["eval case"]
    (agent_span,) = named["invoke_agent signalfloor-agent"]
    chats = named["chat ScriptedChatModel"]
    tools = named["execute_tool search"]
    assert len(chats) == 3
    assert len(tools) == 2

    # Everything is one trace, nested case > agent > model and tool calls.
    assert root.context is not None and agent_span.parent is not None
    assert {s.context.trace_id for s in spans.get_finished_spans() if s.context} == {
        root.context.trace_id
    }
    assert agent_span.parent.span_id == root.context.span_id
    assert agent_span.context is not None
    for child in [*chats, *tools]:
        assert child.parent is not None
        assert child.parent.span_id == agent_span.context.span_id

    assert case.trace_id == format(root.context.trace_id, "032x")
    assert attrs(root) == {
        "signalfloor.case_id": "q1",
        "signalfloor.score": 1.0,
        "signalfloor.supporting_recall": 1.0,
    }
    assert attrs(agent_span)["signalfloor.answer"] == "American"
    assert attrs(agent_span)["signalfloor.searches"] == 2
    assert attrs(chats[0])["signalfloor.tool_calls"] == ("search",)
    assert attrs(chats[2])["gen_ai.usage.input_tokens"] == 120
    assert attrs(chats[2])["gen_ai.usage.output_tokens"] == 8
    assert "gen_ai.usage.input_tokens" not in attrs(chats[0])
    assert attrs(tools[0]) == {
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": "search",
        "gen_ai.tool.call.id": "c1",
        "signalfloor.outcome": "ok",
        "signalfloor.query": "Doctor Strange director",
        "signalfloor.titles": ("Doctor Strange",),
    }


def test_no_prompt_or_passage_text_is_recorded(spans: InMemorySpanExporter) -> None:
    evaluate_case(make_agent(tool_call("Doctor Strange", "c1"), AIMessage("American")), QUESTION)

    recorded = repr([attrs(s) for s in spans.get_finished_spans()])

    assert "directed by" not in recorded
    assert "Nationality?" not in recorded


def test_unknown_tool_is_an_error_span(spans: InMemorySpanExporter) -> None:
    make_agent(tool_call("x", "c1", name="calculator"), AIMessage("42")).answer("Q?")

    (span,) = by_name(spans)["execute_tool calculator"]
    assert span.status.status_code == StatusCode.ERROR
    assert attrs(span)["signalfloor.outcome"] == "unknown_tool"


def test_search_limit_and_finalize(spans: InMemorySpanExporter) -> None:
    many = AIMessage(
        content="",
        tool_calls=[
            {"name": "search", "args": {"query": q}, "id": f"c{i}"}
            for i, q in enumerate(["a", "b"])
        ],
    )
    agent = make_agent(many, tool_call("c", "c3"), AIMessage("done"), max_searches=1)

    agent.answer("Q?")

    named = by_name(spans)
    outcomes = [attrs(s)["signalfloor.outcome"] for s in named["execute_tool search"]]
    assert outcomes == ["ok", "over_budget"]
    assert attrs(named["chat ScriptedChatModel"][-1])["signalfloor.finalize"] is True


def test_recovered_text_tool_calls_are_flagged(spans: InMemorySpanExporter) -> None:
    text_call = AIMessage('{"name": "search", "arguments": {"query": "Doctor Strange"}}')
    make_agent(text_call, AIMessage("American")).answer("Q?")

    first_chat = by_name(spans)["chat ScriptedChatModel"][0]
    assert attrs(first_chat)["signalfloor.recovered_from_text"] is True


def test_no_trace_id_outside_a_span() -> None:
    assert tracing.current_trace_id() is None


def test_configure_sends_to_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    installed: list[TracerProvider] = []
    monkeypatch.setattr(trace, "set_tracer_provider", installed.append)

    provider = tracing.configure("http://localhost:1/v1/traces", service_name="test-agent")

    assert installed == [provider]
    assert provider.resource.attributes["service.name"] == "test-agent"
    processors = provider._active_span_processor._span_processors
    assert processors[0].span_exporter._endpoint == "http://localhost:1/v1/traces"  # type: ignore[attr-defined]
    provider.shutdown()
