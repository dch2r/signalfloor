from pathlib import Path
from typing import Any

import httpx
import pytest

from signalfloor_agent.data import DataError, Passage, build_corpus, load_hotpot, parse_row


def make_row(i: int, titles: tuple[str, str] = ("Alpha", "Beta")) -> dict[str, Any]:
    return {
        "id": f"q{i}",
        "question": f"Question {i}?",
        "answer": f"answer {i}",
        "type": "bridge",
        "level": "easy",
        "supporting_facts": {"title": [titles[0], titles[0], titles[1]], "sent_id": [0, 1, 0]},
        "context": {
            "title": list(titles),
            "sentences": [[f"{titles[0]} is first. ", "It has two sentences."], [f"{titles[1]}."]],
        },
    }


class FakeRowsApi:
    """Stands in for the Hugging Face rows API and records each request."""

    def __init__(self, total: int) -> None:
        self.total = total
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        offset = int(request.url.params["offset"])
        length = int(request.url.params["length"])
        rows = [{"row": make_row(i)} for i in range(offset, min(offset + length, self.total))]
        return httpx.Response(200, json={"rows": rows})


def test_parse_row() -> None:
    q = parse_row(make_row(7))

    assert q.id == "q7"
    assert q.question == "Question 7?"
    assert q.answer == "answer 7"
    assert q.kind == "bridge"
    assert q.supporting_titles == ("Alpha", "Beta")
    assert q.passages[0] == Passage("Alpha", "Alpha is first. It has two sentences.")


def test_parse_row_rejects_unexpected_format() -> None:
    with pytest.raises(DataError, match="unexpected HotpotQA row format"):
        parse_row({"id": "q1"})


def test_corpus_keeps_one_passage_per_title_sorted() -> None:
    a = parse_row(make_row(1, ("Zed", "Alpha")))
    b = parse_row(make_row(2, ("Alpha", "Mid")))

    corpus = build_corpus([a, b])

    assert [p.title for p in corpus] == ["Alpha", "Mid", "Zed"]


def test_downloads_in_pages_and_caches(tmp_path: Path) -> None:
    api = FakeRowsApi(total=500)
    client = httpx.Client(transport=httpx.MockTransport(api))

    first = load_hotpot(150, offset=20, cache_dir=tmp_path, client=client)
    second = load_hotpot(150, offset=20, cache_dir=tmp_path, client=client)

    assert [q.id for q in first.questions] == [f"q{i}" for i in range(20, 170)]
    assert [(r.url.params["offset"], r.url.params["length"]) for r in api.requests] == [
        ("20", "100"),
        ("120", "50"),
    ]
    assert second == first
    assert len(api.requests) == 2, "second load should come from the cache"
    assert (tmp_path / "hotpot_dev_distractor_20_150.json").exists()


def test_fails_when_not_enough_questions(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(FakeRowsApi(total=30)))

    # The second page comes back empty, which ends the download early.
    with pytest.raises(DataError, match="asked for 150 questions from offset 0 but only 30 exist"):
        load_hotpot(150, cache_dir=tmp_path, client=client)


def test_http_errors_become_data_errors(tmp_path: Path) -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))

    with pytest.raises(DataError, match="could not download HotpotQA rows 0-10"):
        load_hotpot(10, cache_dir=tmp_path, client=client)


@pytest.mark.parametrize(("n", "offset", "message"), [(0, 0, "n must be"), (5, -1, "offset")])
def test_rejects_bad_arguments(n: int, offset: int, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        load_hotpot(n, offset=offset)


def test_default_cache_dir_respects_xdg(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from signalfloor_agent.data import default_cache_dir

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert default_cache_dir() == tmp_path / "signalfloor-agent"


def test_creates_and_closes_its_own_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    made: list[httpx.Client] = []
    real_client = httpx.Client

    def fake_client(**kwargs: Any) -> httpx.Client:
        client = real_client(transport=httpx.MockTransport(FakeRowsApi(total=10)))
        made.append(client)
        return client

    monkeypatch.setattr(httpx, "Client", fake_client)

    dataset = load_hotpot(10, cache_dir=tmp_path)

    assert len(dataset.questions) == 10
    assert made[0].is_closed
