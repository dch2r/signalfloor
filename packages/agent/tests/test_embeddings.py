import json

import httpx
import numpy as np
import pytest

from signalfloor_agent.embeddings import NOMIC_PREFIXES, EmbeddingError, OpenAICompatibleEmbedder


class FakeEmbeddingsApi:
    """Returns [length of text, position in batch] as each embedding, in reverse order."""

    def __init__(self) -> None:
        self.batches: list[list[str]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert request.url.path == "/v1/embeddings"
        assert request.headers["Authorization"] == "Bearer secret"
        self.batches.append(body["input"])
        data = [
            {"index": i, "embedding": [float(len(text)), float(i)]}
            for i, text in enumerate(body["input"])
        ]
        return httpx.Response(200, json={"data": list(reversed(data))})


def make(api: FakeEmbeddingsApi, **kwargs: object) -> OpenAICompatibleEmbedder:
    client = httpx.Client(transport=httpx.MockTransport(api))
    return OpenAICompatibleEmbedder(
        base_url="http://test/v1/",
        api_key="secret",
        client=client,
        **kwargs,  # type: ignore[arg-type]
    )


def test_embeds_documents_in_batches_and_keeps_order() -> None:
    api = FakeEmbeddingsApi()
    embedder = make(api, batch_size=2)

    vectors = embedder.embed_documents(["a", "bb", "ccc"])

    assert api.batches == [["a", "bb"], ["ccc"]]
    assert vectors.dtype == np.float32
    assert vectors.tolist() == [[1, 0], [2, 1], [3, 0]]


def test_adds_task_prefixes() -> None:
    api = FakeEmbeddingsApi()
    embedder = make(api, **NOMIC_PREFIXES)

    embedder.embed_documents(["doc"])
    embedder.embed_query("q")

    assert api.batches == [["search_document: doc"], ["search_query: q"]]
    assert "search_document" in embedder.name


def test_query_returns_one_vector() -> None:
    assert make(FakeEmbeddingsApi()).embed_query("abc").tolist() == [3, 0]


def test_no_documents_means_no_requests() -> None:
    api = FakeEmbeddingsApi()

    assert make(api).embed_documents([]).shape == (0, 0)
    assert api.batches == []


def test_http_errors_become_embedding_errors() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    embedder = OpenAICompatibleEmbedder(client=client)

    with pytest.raises(EmbeddingError, match=r"embeddings request to .* failed"):
        embedder.embed_query("x")


@pytest.mark.parametrize(
    ("payload", "message"),
    [({"nope": []}, "unexpected embeddings response"), ({"data": []}, "sent 1 texts but got 0")],
)
def test_bad_responses_raise(payload: dict[str, object], message: str) -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))
    )

    with pytest.raises(EmbeddingError, match=message):
        OpenAICompatibleEmbedder(client=client).embed_query("x")


def test_rejects_bad_batch_size() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        OpenAICompatibleEmbedder(batch_size=0)
