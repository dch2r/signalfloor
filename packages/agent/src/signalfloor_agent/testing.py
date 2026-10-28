"""Fakes for testing code that uses the agent, without a model server."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from typing import Any

import numpy as np
import numpy.typing as npt
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from signalfloor_agent.bm25 import tokenize


class HashingEmbedder:
    """A stand in for a real embedding model.

    Each word is hashed into one of 256 dimensions, so texts that share words get similar
    vectors. That is enough to test dense retrieval without a model server.
    """

    name = "hashing-256"

    def __init__(self) -> None:
        self.documents_embedded = 0

    def embed_documents(self, texts: Sequence[str]) -> npt.NDArray[np.float32]:
        self.documents_embedded += len(texts)
        return np.array([self._vector(t) for t in texts], dtype=np.float32).reshape(len(texts), 256)

    def embed_query(self, text: str) -> npt.NDArray[np.float32]:
        return self._vector(text)

    @staticmethod
    def _vector(text: str) -> npt.NDArray[np.float32]:
        vector = np.zeros(256, dtype=np.float32)
        for word in tokenize(text):
            vector[int(hashlib.md5(word.encode()).hexdigest(), 16) % 256] += 1
        return vector


class ScriptedChatModel(BaseChatModel):
    """A chat model that replies with a fixed list of messages, in order.

    Every call records the messages it was given, so tests can check exactly what the agent
    sent. bind_tools records the tool names and returns the same model.
    """

    replies: list[AIMessage]
    calls: list[list[BaseMessage]] = Field(default_factory=list)
    bound_tools: list[str] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        if len(self.calls) >= len(self.replies):
            raise AssertionError(
                f"model called {len(self.calls) + 1} times but the script has {len(self.replies)}"
            )
        self.calls.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.replies[len(self.calls) - 1])])

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> ScriptedChatModel:
        self.bound_tools = [getattr(t, "name", str(t)) for t in tools]
        return self


def tool_call(query: str, call_id: str = "call-1", name: str = "search") -> AIMessage:
    """An AI message asking to run one search."""
    return AIMessage(
        content="", tool_calls=[{"name": name, "args": {"query": query}, "id": call_id}]
    )
