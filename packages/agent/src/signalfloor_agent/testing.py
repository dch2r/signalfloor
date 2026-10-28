"""Fakes for testing code that uses the agent, without a model server."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence

import numpy as np
import numpy.typing as npt

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
