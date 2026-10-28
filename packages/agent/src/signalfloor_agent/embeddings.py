"""Text embeddings through any OpenAI compatible embeddings API.

By default this talks to a local Ollama server, so it costs nothing. Point base_url and model
at another provider to use a hosted model instead.

Some models expect a task prefix on every input. nomic-embed-text, for example, wants
"search_document: " before passages and "search_query: " before queries. NOMIC_PREFIXES has
those values ready to pass in.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

import httpx
import numpy as np
import numpy.typing as npt

NOMIC_PREFIXES = {"document_prefix": "search_document: ", "query_prefix": "search_query: "}


class EmbeddingError(RuntimeError):
    """The embeddings API failed or returned something unexpected."""


class Embedder(Protocol):
    @property
    def name(self) -> str:
        """Identifies the model and settings, used to key cached embeddings."""
        ...

    def embed_documents(self, texts: Sequence[str]) -> npt.NDArray[np.float32]: ...

    def embed_query(self, text: str) -> npt.NDArray[np.float32]: ...


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        model: str = "nomic-embed-text",
        *,
        base_url: str = "http://localhost:11434/v1",
        api_key: str = "ollama",
        document_prefix: str = "",
        query_prefix: str = "",
        batch_size: int = 32,
        client: httpx.Client | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        self.model = model
        self.document_prefix = document_prefix
        self.query_prefix = query_prefix
        self.batch_size = batch_size
        self._url = base_url.rstrip("/") + "/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._client = client or httpx.Client(timeout=300)

    @property
    def name(self) -> str:
        return f"{self.model}|{self.document_prefix}|{self.query_prefix}"

    def embed_documents(self, texts: Sequence[str]) -> npt.NDArray[np.float32]:
        batches = [
            self._embed([self.document_prefix + t for t in texts[i : i + self.batch_size]])
            for i in range(0, len(texts), self.batch_size)
        ]
        return np.vstack(batches) if batches else np.empty((0, 0), dtype=np.float32)

    def embed_query(self, text: str) -> npt.NDArray[np.float32]:
        result: npt.NDArray[np.float32] = self._embed([self.query_prefix + text])[0]
        return result

    def _embed(self, inputs: list[str]) -> npt.NDArray[np.float32]:
        try:
            response = self._client.post(
                self._url, json={"model": self.model, "input": inputs}, headers=self._headers
            )
            response.raise_for_status()
            items = sorted(response.json()["data"], key=lambda item: item["index"])
        except httpx.HTTPError as e:
            raise EmbeddingError(f"embeddings request to {self._url} failed: {e}") from e
        except (KeyError, TypeError, ValueError) as e:
            raise EmbeddingError(f"unexpected embeddings response: {e!r}") from e
        if len(items) != len(inputs):
            raise EmbeddingError(f"sent {len(inputs)} texts but got {len(items)} embeddings back")
        return np.array([item["embedding"] for item in items], dtype=np.float32)
