"""A LangGraph agent that answers multi-hop questions by searching a passage corpus.

The graph has three nodes:

    agent     the model reads the conversation and either calls the search tool or answers
    search    runs every search the model asked for and adds the passages to the conversation
    finalize  asks for an answer without tools once the search budget is used up

agent loops through search until it answers or reaches max_searches. Capping searches keeps
a confused model from looping forever and keeps the cost of each question predictable.
"""

from __future__ import annotations

import json
import operator
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from opentelemetry.trace import Span, StatusCode

from signalfloor_agent.data import Passage
from signalfloor_agent.retrieval import Retriever
from signalfloor_agent.tracing import tracer

SYSTEM_PROMPT = """You answer questions using a search tool over Wikipedia passages.

Questions usually need two facts from two different passages. Search for one fact at a time.
If the first search names a person, place or work you need to know more about, search for it.

When you know the answer, reply with only the answer: a name, a short phrase, a number, or
yes or no. Do not explain."""

# A second prompt aimed at the two failures seen on real questions: answering "Yes" to
# questions that are not yes or no questions, and stopping after one search.
SYSTEM_PROMPT_V2 = """You answer questions using a search tool over Wikipedia passages.

Most questions need two facts from two different passages, so you usually need two searches.
Search for one thing at a time. After the first search, find the person, place or work you
still need to know about and search for it.

Answer yes or no only when the question itself is a yes or no question, such as one that
starts with Are, Is, Was, Were, Do or Did. Otherwise answer with the name, phrase or number
the question asks for.

Reply with only the answer. Do not explain."""

PROMPTS = {"v1": SYSTEM_PROMPT, "v2": SYSTEM_PROMPT_V2}

FINALIZE_PROMPT = (
    "You have used all your searches. Give your best answer now. "
    "Reply with only the answer, no explanation."
)

_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)
_ANSWER_PREFIX = re.compile(r"^\s*(final\s+)?answer\s*:\s*", re.IGNORECASE)
_TOOL_CALL_WRAPPER = re.compile(r"</?tool_call>|^```(json)?|```$", re.MULTILINE)


@dataclass(frozen=True)
class AgentConfig:
    max_searches: int = 4
    passages_per_search: int = 4
    system_prompt: str = SYSTEM_PROMPT

    def __post_init__(self) -> None:
        if self.max_searches < 1:
            raise ValueError(f"max_searches must be at least 1, got {self.max_searches}")
        if self.passages_per_search < 1:
            raise ValueError(
                f"passages_per_search must be at least 1, got {self.passages_per_search}"
            )


@dataclass(frozen=True)
class AgentResult:
    answer: str
    searches: tuple[str, ...]
    retrieved_titles: tuple[str, ...]
    hit_search_limit: bool
    messages: tuple[AnyMessage, ...] = field(repr=False)


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    searches: Annotated[list[str], operator.add]
    retrieved_titles: Annotated[list[str], operator.add]


class Agent:
    def __init__(
        self, model: BaseChatModel, retriever: Retriever, config: AgentConfig | None = None
    ) -> None:
        self.config = config or AgentConfig()
        self.retriever = retriever

        @tool
        def search(query: str) -> str:
            """Search Wikipedia passages. Use a short query naming one person, place or thing."""
            return format_passages(retriever.search(query, self.config.passages_per_search))

        self._search_tool = search
        self._model = model
        self._model_with_tools = model.bind_tools([search])
        self.graph = self._build_graph()

    def answer(self, question: str) -> AgentResult:
        initial: AgentState = {
            "messages": [SystemMessage(self.config.system_prompt), HumanMessage(question)],
            "searches": [],
            "retrieved_titles": [],
        }
        # Each search round is two graph steps, plus the final answer and some slack.
        limit = 2 * self.config.max_searches + 5
        with tracer.start_as_current_span(
            "invoke_agent signalfloor-agent",
            attributes={
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": "signalfloor-agent",
            },
        ) as span:
            state = self.graph.invoke(initial, config={"recursion_limit": limit})
            messages: list[AnyMessage] = state["messages"]
            result = AgentResult(
                answer=extract_answer(_text(messages[-1])),
                searches=tuple(state["searches"]),
                retrieved_titles=tuple(dict.fromkeys(state["retrieved_titles"])),
                hit_search_limit=any(
                    isinstance(m, HumanMessage) and m.content == FINALIZE_PROMPT for m in messages
                ),
                messages=tuple(messages),
            )
            span.set_attributes(
                {
                    "signalfloor.answer": result.answer,
                    "signalfloor.searches": len(result.searches),
                    "signalfloor.hit_search_limit": result.hit_search_limit,
                }
            )
        return result

    def _build_graph(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("agent", self._call_model)
        graph.add_node("search", self._run_searches)
        graph.add_node("finalize", self._finalize)
        graph.add_edge(START, "agent")
        graph.add_conditional_edges("agent", self._route)
        graph.add_edge("search", "agent")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _call_model(self, state: AgentState) -> dict[str, list[AnyMessage]]:
        with self._chat_span() as span:
            reply = self._model_with_tools.invoke(state["messages"])
            message = recover_text_tool_call(reply, f"text-call-{len(state['messages'])}")
            _record_reply(span, message)
        return {"messages": [message]}

    @contextmanager
    def _chat_span(self) -> Iterator[Span]:
        model = getattr(self._model, "model_name", None) or type(self._model).__name__
        with tracer.start_as_current_span(
            f"chat {model}",
            attributes={"gen_ai.operation.name": "chat", "gen_ai.request.model": model},
        ) as span:
            yield span

    def _route(self, state: AgentState) -> str:
        last = state["messages"][-1]
        if not isinstance(last, AIMessage) or not last.tool_calls:
            return END
        if len(state["searches"]) >= self.config.max_searches:
            return "finalize"
        return "search"

    def _run_searches(self, state: AgentState) -> dict[str, list[Any]]:
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        budget = self.config.max_searches - len(state["searches"])
        messages: list[AnyMessage] = []
        queries: list[str] = []
        titles: list[str] = []
        for i, call in enumerate(last.tool_calls):
            with tracer.start_as_current_span(
                f"execute_tool {call['name']}",
                attributes={
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": call["name"],
                    "gen_ai.tool.call.id": call["id"] or "",
                },
            ) as span:
                # Every tool call needs a reply, even ones we refuse, or the model API rejects
                # the conversation on the next turn.
                if call["name"] != "search":
                    content = f"Unknown tool {call['name']!r}. The only tool is search."
                    span.set_attribute("signalfloor.outcome", "unknown_tool")
                    span.set_status(StatusCode.ERROR, "model called a tool that does not exist")
                elif i >= budget:
                    content = "Search limit reached. Answer with what you have."
                    span.set_attribute("signalfloor.outcome", "over_budget")
                else:
                    query = str(call["args"].get("query", ""))
                    passages = self.retriever.search(query, self.config.passages_per_search)
                    queries.append(query)
                    titles.extend(p.title for p in passages)
                    content = format_passages(passages)
                    span.set_attributes(
                        {
                            "signalfloor.outcome": "ok",
                            "signalfloor.query": query,
                            "signalfloor.titles": [p.title for p in passages],
                        }
                    )
            messages.append(ToolMessage(content=content, tool_call_id=call["id"]))
        return {"messages": messages, "searches": queries, "retrieved_titles": titles}

    def _finalize(self, state: AgentState) -> dict[str, list[AnyMessage]]:
        # The last message asks for a tool that will not run. Answer it so the conversation
        # stays valid, then ask for a final answer from a model with no tools bound.
        last = state["messages"][-1]
        assert isinstance(last, AIMessage)
        skipped: list[AnyMessage] = [
            ToolMessage(content="Search limit reached.", tool_call_id=c["id"])
            for c in last.tool_calls
        ]
        prompt = HumanMessage(FINALIZE_PROMPT)
        with self._chat_span() as span:
            span.set_attribute("signalfloor.finalize", True)
            reply = self._model.invoke([*state["messages"], *skipped, prompt])
            _record_reply(span, reply)
        return {"messages": [*skipped, prompt, reply]}


def _record_reply(span: Span, message: AnyMessage) -> None:
    usage = getattr(message, "usage_metadata", None)
    if usage:
        span.set_attributes(
            {
                "gen_ai.usage.input_tokens": usage["input_tokens"],
                "gen_ai.usage.output_tokens": usage["output_tokens"],
            }
        )
    span.set_attributes(
        {
            "signalfloor.tool_calls": [c["name"] for c in getattr(message, "tool_calls", [])],
            "signalfloor.recovered_from_text": bool(
                message.response_metadata.get("recovered_from_text")
            ),
        }
    )


def recover_text_tool_call(message: AnyMessage, call_id: str) -> AnyMessage:
    """Turn a tool call the model wrote as plain JSON text into a real tool call.

    Small models sometimes reply with {"name": "search", "arguments": {...}} as text instead
    of a structured tool call. Without this, that text would be taken as the final answer.
    """
    if not isinstance(message, AIMessage) or message.tool_calls:
        return message
    text = _TOOL_CALL_WRAPPER.sub("", _THINK.sub("", _text(message))).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return message
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        return message
    args = data.get("arguments", data.get("parameters"))
    if not isinstance(args, dict):
        return message
    return AIMessage(
        content="",
        tool_calls=[{"name": data["name"], "args": args, "id": call_id}],
        response_metadata={"recovered_from_text": True},
    )


def format_passages(passages: Sequence[Passage]) -> str:
    if not passages:
        return "No passages found."
    return "\n\n".join(f"[{p.title}] {p.text}" for p in passages)


def extract_answer(text: str) -> str:
    """Pull a short answer out of a model reply that may include thinking or a label."""
    text = _THINK.sub("", text).strip()
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return ""
    answer = _ANSWER_PREFIX.sub("", lines[-1]).strip()
    return answer.strip("*\"' ").removesuffix(".").strip()


def _text(message: AnyMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return " ".join(
        part["text"] if isinstance(part, dict) and "text" in part else str(part) for part in content
    )


def openai_compatible_chat_model(
    model: str = "qwen3:1.7b",
    *,
    base_url: str = "http://localhost:11434/v1",
    api_key: str = "ollama",
    disable_thinking: bool = True,
) -> BaseChatModel:
    """A chat model on any OpenAI compatible API. By default, a local model served by Ollama.

    Thinking is off by default. On a laptop CPU it made each step about 12 times slower with
    no better tool calls.
    """
    from langchain_openai import ChatOpenAI

    extra: dict[str, Any] = {"reasoning_effort": "none"} if disable_thinking else {}
    return ChatOpenAI(model=model, base_url=base_url, api_key=api_key, temperature=0, **extra)  # type: ignore[arg-type]
