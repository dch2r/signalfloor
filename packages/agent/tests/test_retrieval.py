from pathlib import Path

import pytest

from signalfloor_agent.data import Passage, Question
from signalfloor_agent.embeddings import Embedder
from signalfloor_agent.retrieval import (
    DenseRetriever,
    HybridRetriever,
    KeywordRetriever,
    recall_at_k,
    reciprocal_rank_fusion,
)
from signalfloor_agent.testing import HashingEmbedder

CORPUS = (
    Passage("Scott Derrickson", "Scott Derrickson is an American director and screenwriter."),
    Passage("Ed Wood", "Edward Davis Wood Jr. was an American filmmaker and actor."),
    Passage("Doctor Strange", "Doctor Strange is a 2016 superhero film directed by Derrickson."),
    Passage("Paris", "Paris is the capital and largest city of France."),
)


def titles(passages: list[Passage]) -> list[str]:
    return [p.title for p in passages]


def question(text: str, *supporting: str) -> Question:
    return Question("q", text, "a", "bridge", "hard", supporting, ())


def test_keyword_retriever_uses_titles_and_text() -> None:
    retriever = KeywordRetriever(CORPUS)

    assert titles(retriever.search("capital of France", k=1)) == ["Paris"]
    assert titles(retriever.search("Ed Wood", k=1)) == ["Ed Wood"]


def test_dense_retriever_ranks_by_similarity(embedder: Embedder) -> None:
    retriever = DenseRetriever(CORPUS, embedder)

    assert titles(retriever.search("superhero film 2016", k=1)) == ["Doctor Strange"]
    assert len(retriever.search("anything", k=3)) == 3


def test_dense_retriever_caches_embeddings(tmp_path: Path, embedder: HashingEmbedder) -> None:
    DenseRetriever(CORPUS, embedder, cache_dir=tmp_path)
    DenseRetriever(CORPUS, embedder, cache_dir=tmp_path)

    assert embedder.documents_embedded == len(CORPUS), "second build should use the cache"
    assert len(list(tmp_path.glob("embeddings-*.npy"))) == 1

    DenseRetriever(CORPUS[:2], embedder, cache_dir=tmp_path)
    assert len(list(tmp_path.glob("embeddings-*.npy"))) == 2, "a new corpus needs a new cache"


def test_rrf_matches_the_formula() -> None:
    # Item 7 is 1st and 2nd: 1/61 + 1/62. Item 3 is 2nd and 1st: same total, smaller id wins.
    # Item 5 is only 3rd in the first ranking: 1/63.
    assert reciprocal_rank_fusion([[7, 3, 5], [3, 7]]) == [3, 7, 5]


def test_rrf_rewards_items_both_rankings_agree_on() -> None:
    # Item 2 is never first but is near the top of both lists, so it beats both winners.
    assert reciprocal_rank_fusion([[0, 2, 9, 8], [1, 2, 7, 6]], k=1)[0] == 2


def test_hybrid_finds_what_either_retriever_finds(embedder: Embedder) -> None:
    hybrid = HybridRetriever(KeywordRetriever(CORPUS), DenseRetriever(CORPUS, embedder))

    found = titles(hybrid.search("Derrickson superhero film", k=2))

    assert set(found) == {"Scott Derrickson", "Doctor Strange"}


def test_hybrid_needs_the_same_corpus(embedder: Embedder) -> None:
    with pytest.raises(ValueError, match="same corpus"):
        HybridRetriever(KeywordRetriever(CORPUS), DenseRetriever(CORPUS[:2], embedder))


def test_recall_at_k_counts_supporting_passages_found() -> None:
    retriever = KeywordRetriever(CORPUS)
    questions = [
        question("Derrickson superhero film", "Scott Derrickson", "Doctor Strange"),
        question("capital of France", "Paris", "Ed Wood"),
    ]

    # First question finds both at k=2. Second finds Paris but not Ed Wood.
    assert recall_at_k(retriever, questions, k=2) == pytest.approx((1 + 0.5) / 2)


def test_recall_needs_questions() -> None:
    with pytest.raises(ValueError, match="at least one question"):
        recall_at_k(KeywordRetriever(CORPUS), [], k=2)
