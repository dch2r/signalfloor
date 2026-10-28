import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from signalfloor_agent.agent import (
    FINALIZE_PROMPT,
    Agent,
    AgentConfig,
    extract_answer,
    format_passages,
    openai_compatible_chat_model,
    recover_text_tool_call,
)
from signalfloor_agent.data import Passage
from signalfloor_agent.retrieval import KeywordRetriever
from signalfloor_agent.testing import ScriptedChatModel, tool_call

CORPUS = (
    Passage("Doctor Strange", "Doctor Strange is a 2016 film directed by Scott Derrickson."),
    Passage("Scott Derrickson", "Scott Derrickson is an American director and screenwriter."),
    Passage("Paris", "Paris is the capital of France."),
)


def make_agent(*replies: AIMessage, **config: int) -> tuple[Agent, ScriptedChatModel]:
    model = ScriptedChatModel(replies=list(replies))
    agent = Agent(model, KeywordRetriever(CORPUS), AgentConfig(passages_per_search=1, **config))
    return agent, model


def test_two_hop_question() -> None:
    agent, model = make_agent(
        tool_call("Doctor Strange director", "c1"),
        tool_call("Scott Derrickson nationality", "c2"),
        AIMessage("American"),
    )

    result = agent.answer("What nationality is the director of Doctor Strange?")

    assert result.answer == "American"
    assert result.searches == ("Doctor Strange director", "Scott Derrickson nationality")
    assert result.retrieved_titles == ("Doctor Strange", "Scott Derrickson")
    assert not result.hit_search_limit
    assert model.bound_tools == ["search"]

    first_call = model.calls[0]
    assert isinstance(first_call[0], SystemMessage)
    assert isinstance(first_call[1], HumanMessage)
    assert first_call[1].content == "What nationality is the director of Doctor Strange?"

    # The second model call sees the first search result, tied to the right tool call.
    tool_reply = model.calls[1][-1]
    assert isinstance(tool_reply, ToolMessage)
    assert tool_reply.tool_call_id == "c1"
    assert str(tool_reply.content).startswith("[Doctor Strange] Doctor Strange is a 2016 film")


def test_answers_without_searching() -> None:
    agent, model = make_agent(AIMessage("Paris"))

    result = agent.answer("What is the capital of France?")

    assert result.answer == "Paris"
    assert result.searches == ()
    assert len(model.calls) == 1


def test_stops_at_the_search_limit_and_asks_for_an_answer() -> None:
    agent, model = make_agent(
        tool_call("one", "c1"),
        tool_call("two", "c2"),
        tool_call("three", "c3"),
        AIMessage("Answer: American."),
        max_searches=2,
    )

    result = agent.answer("Question?")

    assert result.answer == "American"
    assert result.searches == ("one", "two")
    assert result.hit_search_limit

    final_call = model.calls[-1]
    assert isinstance(final_call[-1], HumanMessage)
    assert final_call[-1].content == FINALIZE_PROMPT
    # The unanswered third tool call still gets a reply so the conversation stays valid.
    skipped = final_call[-2]
    assert isinstance(skipped, ToolMessage)
    assert skipped.tool_call_id == "c3"
    assert skipped.content == "Search limit reached."


def test_parallel_calls_beyond_the_budget_are_refused() -> None:
    many = AIMessage(
        content="",
        tool_calls=[
            {"name": "search", "args": {"query": q}, "id": f"c{i}"}
            for i, q in enumerate(["Paris", "Scott Derrickson", "Doctor Strange"])
        ],
    )
    agent, model = make_agent(many, AIMessage("done"), max_searches=2)

    result = agent.answer("Question?")

    assert result.searches == ("Paris", "Scott Derrickson")
    replies = [m for m in model.calls[1] if isinstance(m, ToolMessage)]
    assert [r.tool_call_id for r in replies] == ["c0", "c1", "c2"]
    assert replies[2].content == "Search limit reached. Answer with what you have."


def test_unknown_tools_get_an_error_reply() -> None:
    agent, model = make_agent(tool_call("x", "c1", name="calculator"), AIMessage("42"))

    result = agent.answer("Question?")

    assert result.answer == "42"
    assert result.searches == ()
    reply = model.calls[1][-1]
    assert isinstance(reply, ToolMessage)
    assert reply.content == "Unknown tool 'calculator'. The only tool is search."


def test_handles_list_content_from_the_model() -> None:
    agent, _ = make_agent(AIMessage(content=[{"type": "text", "text": "Paris"}, "France"]))

    assert agent.answer("Q?").answer == "Paris France"


@pytest.mark.parametrize(
    ("reply", "expected"),
    [
        ("American", "American"),
        ("<think>hmm, the director is American</think>\nAmerican", "American"),
        ("Answer: Tim Burton.", "Tim Burton"),
        ("Final answer: **yes**", "yes"),
        ("Let me think.\n\nThe answer is below.\n1994", "1994"),
        ('"Paris"', "Paris"),
        ("", ""),
        ("<think>only thinking</think>", ""),
    ],
)
def test_extract_answer(reply: str, expected: str) -> None:
    assert extract_answer(reply) == expected


def test_format_passages() -> None:
    assert format_passages([]) == "No passages found."
    assert format_passages(CORPUS[2:]) == "[Paris] Paris is the capital of France."


def test_the_search_tool_works_on_its_own() -> None:
    agent, _ = make_agent()

    assert agent._search_tool.invoke({"query": "capital of France"}).startswith("[Paris]")


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [({"max_searches": 0}, "max_searches"), ({"passages_per_search": 0}, "passages_per_search")],
)
def test_config_validation(kwargs: dict[str, int], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        AgentConfig(**kwargs)


def test_model_factory_turns_thinking_off_by_default() -> None:
    quiet = openai_compatible_chat_model()
    thinking = openai_compatible_chat_model("other-model", disable_thinking=False)

    assert getattr(quiet, "reasoning_effort", None) == "none"
    assert getattr(quiet, "temperature", None) == 0
    assert getattr(thinking, "reasoning_effort", None) is None
    assert getattr(thinking, "model_name", None) == "other-model"


def test_scripted_model_fails_loudly_when_the_script_runs_out() -> None:
    agent, _ = make_agent()

    with pytest.raises(AssertionError, match="model called 1 times but the script has 0"):
        agent.answer("Q?")


@pytest.mark.parametrize(
    "text",
    [
        '{"name": "search", "arguments": {"query": "Corliss Archer"}}',
        '<tool_call>\n{"name": "search", "arguments": {"query": "Corliss Archer"}}\n</tool_call>',
        '```json\n{"name": "search", "parameters": {"query": "Corliss Archer"}}\n```',
    ],
)
def test_recovers_tool_calls_written_as_text(text: str) -> None:
    agent, model = make_agent(AIMessage(text), AIMessage("Chief of Protocol"))

    result = agent.answer("What position did the actress hold?")

    assert result.searches == ("Corliss Archer",)
    assert result.answer == "Chief of Protocol"
    reply = model.calls[1][-1]
    assert isinstance(reply, ToolMessage)
    assert reply.tool_call_id == "text-call-2"


@pytest.mark.parametrize(
    "text",
    [
        "American",
        "[1, 2]",
        '{"answer": "American"}',
        '{"name": "search", "arguments": "Corliss Archer"}',
    ],
)
def test_leaves_normal_answers_alone(text: str) -> None:
    message = AIMessage(text)

    assert recover_text_tool_call(message, "x") is message


def test_does_not_touch_real_tool_calls() -> None:
    message = tool_call("q")

    assert recover_text_tool_call(message, "x") is message
