"""Find the passages that answer a query.

Three retrievers share one interface:

- KeywordRetriever ranks passages with BM25. Strong on exact names and rare words.
- DenseRetriever ranks by cosine similarity of embeddings. Strong on paraphrases.
- HybridRetriever merges both rankings with reciprocal rank fusion.

Reciprocal rank fusion gives each passage 1 / (k + rank) from every ranking it appears in and
sorts by the total. It only looks at ranks, so the two very different score scales never
have to be calibrated against each other. k = 60 is the value from the original paper
(Cormack, Clarke and Buettcher, 2009).

Each passage is indexed as "title. text" because HotpotQA questions often name the title.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import numpy as np
import numpy.typing as npt

from signalfloor_agent.bm25 import BM25
from signalfloor_agent.data import Passage, Question
from signalfloor_agent.embeddings import Embedder

RRF_K = 60


class Retriever(Protocol):
    def search(self, query: str, k: int = 5) -> list[Passage]: ...


def passage_text(p: Passage) -> str:
    return f"{p.title}. {p.text}"


class KeywordRetriever:
    def __init__(self, corpus: Sequence[Passage]) -> None:
        self.corpus = tuple(corpus)
        self._bm25 = BM25([passage_text(p) for p in self.corpus])

    def search(self, query: str, k: int = 5) -> list[Passage]:
        return [self.corpus[i] for i in self.ranking(query, k)]

    def ranking(self, query: str, depth: int) -> list[int]:
        return [i for i, _ in self._bm25.search(query, depth)]


class DenseRetriever:
    def __init__(
        self, corpus: Sequence[Passage], embedder: Embedder, *, cache_dir: Path | None = None
    ) -> None:
        self.corpus = tuple(corpus)
        self.embedder = embedder
        texts = [passage_text(p) for p in self.corpus]
        self._vectors = _normalize(_cached_embeddings(texts, embedder, cache_dir))

    def search(self, query: str, k: int = 5) -> list[Passage]:
        return [self.corpus[i] for i in self.ranking(query, k)]

    def ranking(self, query: str, depth: int) -> list[int]:
        query_vector = _normalize(self.embedder.embed_query(query)[np.newaxis])[0]
        similarity = self._vectors @ query_vector
        # Stable sort on negated similarity keeps ties in corpus order.
        order = np.argsort(-similarity, kind="stable")[:depth]
        return [int(i) for i in order]


class HybridRetriever:
    def __init__(
        self, keyword: KeywordRetriever, dense: DenseRetriever, *, depth: int = 50
    ) -> None:
        if keyword.corpus != dense.corpus:
            raise ValueError("keyword and dense retrievers must index the same corpus")
        self.corpus = keyword.corpus
        self.keyword = keyword
        self.dense = dense
        self.depth = depth

    def search(self, query: str, k: int = 5) -> list[Passage]:
        depth = max(k, self.depth)
        fused = reciprocal_rank_fusion(
            [self.keyword.ranking(query, depth), self.dense.ranking(query, depth)]
        )
        return [self.corpus[i] for i in fused[:k]]


def reciprocal_rank_fusion(rankings: Sequence[Sequence[int]], k: int = RRF_K) -> list[int]:
    """Merge rankings of item ids. Ranks start at 1. Ties go to the smaller id."""
    scores: dict[int, float] = defaultdict(float)
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] += 1 / (k + rank)
    return sorted(scores, key=lambda item: (-scores[item], item))


def recall_at_k(retriever: Retriever, questions: Sequence[Question], k: int) -> float:
    """Share of supporting passages that show up in the top k results, averaged over questions."""
    if not questions:
        raise ValueError("need at least one question")
    total = 0.0
    for q in questions:
        found = {p.title for p in retriever.search(q.question, k)}
        total += len(found & set(q.supporting_titles)) / len(q.supporting_titles)
    return total / len(questions)


def _normalize(vectors: npt.NDArray[np.float32]) -> npt.NDArray[np.float32]:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    result: npt.NDArray[np.float32] = (vectors / np.where(norms == 0, 1, norms)).astype(np.float32)
    return result


def _cached_embeddings(
    texts: Sequence[str], embedder: Embedder, cache_dir: Path | None
) -> npt.NDArray[np.float32]:
    if cache_dir is None:
        return embedder.embed_documents(texts)

    digest = hashlib.sha256(embedder.name.encode())
    for text in texts:
        digest.update(b"\0" + text.encode())
    path = cache_dir / f"embeddings-{digest.hexdigest()[:20]}.npy"
    if path.exists():
        cached: npt.NDArray[np.float32] = np.load(path)
        return cached

    vectors = embedder.embed_documents(texts)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.save(path, vectors)
    return vectors
