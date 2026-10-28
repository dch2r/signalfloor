import math

import pytest

from signalfloor_agent.bm25 import BM25, tokenize

DOCS = [
    "Scott Derrickson is an American director.",
    "Ed Wood was an American filmmaker and actor.",
    "The film was released in 1994 and the film won awards.",
    "Paris is the capital of France.",
]


def test_tokenize_lowercases_and_drops_stopwords() -> None:
    assert tokenize("The Film, was RELEASED in 1994!") == ["film", "released", "1994"]


def test_finds_the_document_with_the_rare_word() -> None:
    results = BM25(DOCS).search("Who is Derrickson?")

    assert results[0][0] == 0
    assert len(results) == 1


def test_rare_words_outweigh_common_ones() -> None:
    # "american" is in two documents, "filmmaker" only in one.
    results = BM25(DOCS).search("american filmmaker")

    assert [doc for doc, _ in results] == [1, 0]


def test_matches_the_formula_by_hand() -> None:
    bm25 = BM25(["apple banana", "apple apple cherry", "date"], k1=1.2, b=0.75)

    (doc, score), *_ = bm25.search("cherry")

    # cherry appears once, in doc 1 of 3. Lengths are 2, 3 and 1, so the average is 2.
    idf = math.log(1 + (3 - 1 + 0.5) / (1 + 0.5))
    norm = 1 - 0.75 + 0.75 * 3 / 2
    assert doc == 1
    assert score == pytest.approx(idf * 1 * 2.2 / (1 + 1.2 * norm))


def test_repeating_a_word_helps_with_diminishing_returns() -> None:
    bm25 = BM25(["film", "film film", "film film film film", "other words here now"], b=0)
    scores = dict(bm25.search("film"))

    assert scores[1] > scores[0]
    assert scores[2] - scores[1] < scores[1] - scores[0]


def test_unknown_or_empty_queries_return_nothing() -> None:
    bm25 = BM25(DOCS)

    assert bm25.search("zebra") == []
    assert bm25.search("the of and") == []


def test_k_limits_results_and_ties_break_by_index() -> None:
    bm25 = BM25(["cat", "cat", "cat"])

    assert [doc for doc, _ in bm25.search("cat", k=2)] == [0, 1]


def test_needs_documents() -> None:
    with pytest.raises(ValueError, match="at least one document"):
        BM25([])
