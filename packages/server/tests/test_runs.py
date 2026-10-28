import uuid
from typing import Any

import pytest
from fastapi.testclient import TestClient

from signalfloor_server.schemas import MAX_CASES


def run_body(name: str = "baseline", scores: list[float] | None = None, **labels: str) -> Any:
    scores = [0.5, 1.0, 0.0, 0.5] if scores is None else scores
    return {
        "name": name,
        "labels": labels,
        "cases": [{"id": f"q{i}", "score": s} for i, s in enumerate(scores)],
    }


def upload(client: TestClient, *args: Any, **kwargs: Any) -> dict[str, Any]:
    response = client.post("/runs", json=run_body(*args, **kwargs))
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def test_upload_and_fetch_a_run(client: TestClient) -> None:
    created = upload(client, "v1", model="qwen3:1.7b")

    assert created["name"] == "v1"
    assert created["labels"] == {"model": "qwen3:1.7b"}
    assert created["n_cases"] == 4
    assert created["mean_score"] == 0.5
    uuid.UUID(created["id"])
    assert created["created_at"]

    assert client.get(f"/runs/{created['id']}").json() == created


def test_list_runs_newest_first(client: TestClient) -> None:
    names = ["a", "b", "c"]
    for name in names:
        upload(client, name)

    listed = client.get("/runs").json()

    assert [r["name"] for r in listed] == ["c", "b", "a"]


def test_list_pagination(client: TestClient) -> None:
    for name in ["a", "b", "c"]:
        upload(client, name)

    page = client.get("/runs", params={"limit": 2, "offset": 1}).json()

    assert [r["name"] for r in page] == ["b", "a"]


def test_list_filters_by_labels(client: TestClient) -> None:
    upload(client, "a", prompt="v1", model="m")
    upload(client, "b", prompt="v2", model="m")
    upload(client, "c", prompt="v2", model="other")

    def names(*labels: str) -> list[str]:
        response = client.get("/runs", params={"label": list(labels)})
        return sorted(r["name"] for r in response.json())

    assert names("prompt=v2") == ["b", "c"]
    assert names("prompt=v2", "model=m") == ["b"]
    assert names("prompt=v3") == []


@pytest.mark.parametrize("bad", ["prompt", "=v1"])
def test_bad_label_filter(client: TestClient, bad: str) -> None:
    response = client.get("/runs", params={"label": bad})

    assert response.status_code == 422
    assert "key=value" in response.json()["detail"]


def test_delete_a_run(client: TestClient) -> None:
    run_id = upload(client)["id"]

    assert client.delete(f"/runs/{run_id}").status_code == 204
    assert client.get(f"/runs/{run_id}").status_code == 404
    assert client.delete(f"/runs/{run_id}").status_code == 404


def test_missing_run(client: TestClient) -> None:
    response = client.get(f"/runs/{uuid.uuid4()}")

    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"name": "x", "cases": []}, "at least 1"),
        ({"name": "", "cases": [{"id": "a", "score": 1}]}, "at least 1 character"),
        ({"name": "x", "cases": [{"id": "a", "score": "high"}]}, "valid number"),
        ({"name": "x", "cases": [{"id": "", "score": 1}]}, "at least 1 character"),
        (
            {"name": "x", "cases": [{"id": "a", "score": 1}, {"id": "a", "score": 0}]},
            "case ids must be unique, 1 repeated (e.g. a)",
        ),
        ({"name": "x", "labels": {"k": 1}, "cases": [{"id": "a", "score": 1}]}, "valid string"),
    ],
)
def test_rejects_bad_uploads(client: TestClient, body: Any, message: str) -> None:
    response = client.post("/runs", json=body)

    assert response.status_code == 422
    assert message in response.text


@pytest.mark.parametrize("score", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_rejects_non_finite_scores(client: TestClient, score: str) -> None:
    # Not valid JSON, but Python's json module writes NaN and Infinity, so clients do send them.
    # The error response echoes the input back, which used to crash it into a 500.
    body = '{"name": "x", "cases": [{"id": "a", "score": ' + score + "}]}"

    response = client.post("/runs", content=body, headers={"content-type": "application/json"})

    assert response.status_code == 422
    assert "finite number" in response.text
    assert response.json()["detail"][0]["input"] in {"nan", "inf", "-inf"}


def test_rejects_too_many_cases(client: TestClient) -> None:
    body = {"name": "x", "cases": [{"id": str(i), "score": 0} for i in range(MAX_CASES + 1)]}

    response = client.post("/runs", json=body)

    assert response.status_code == 422
    assert f"at most {MAX_CASES}" in response.text
    # The rejected cases are not echoed back.
    assert len(response.content) < 1000


def test_compare_finds_a_regression(client: TestClient) -> None:
    baseline = upload(client, "base", [1.0] * 50 + [0.0] * 50)["id"]
    candidate = upload(client, "cand", [1.0] * 20 + [0.0] * 80)["id"]

    response = client.get(f"/runs/{baseline}/compare/{candidate}", params={"seed": 0})

    assert response.status_code == 200
    result = response.json()
    assert result["verdict"] == "regression"
    assert result["baseline_id"] == baseline
    assert result["candidate_id"] == candidate
    assert result["delta"] == pytest.approx(-0.3)
    assert result["ci_high"] < 0
    assert result["n_cases"] == 100
    assert result["n_resamples"] == 10_000


def test_compare_matches_the_library(client: TestClient) -> None:
    from signalfloor.compare import paired_bootstrap

    base_scores = [0.1 * (i % 10) for i in range(40)]
    cand_scores = [min(1.0, s + 0.05 * (i % 3 - 1)) for i, s in enumerate(base_scores)]
    baseline = upload(client, "base", base_scores)["id"]
    candidate = upload(client, "cand", cand_scores)["id"]

    api = client.get(
        f"/runs/{baseline}/compare/{candidate}",
        params={"seed": 7, "n_resamples": 2000, "confidence": 0.9},
    ).json()
    lib = paired_bootstrap(
        {f"q{i}": s for i, s in enumerate(base_scores)},
        {f"q{i}": s for i, s in enumerate(cand_scores)},
        seed=7,
        n_resamples=2000,
        confidence=0.9,
    )

    assert api["ci_low"] == lib.ci_low
    assert api["ci_high"] == lib.ci_high
    assert api["verdict"] == lib.verdict.value


def test_compare_runs_with_different_cases(client: TestClient) -> None:
    baseline = upload(client, "base", [1.0, 0.0, 1.0])["id"]
    candidate = upload(client, "cand", [1.0, 0.0])["id"]

    response = client.get(f"/runs/{baseline}/compare/{candidate}")

    assert response.status_code == 422
    assert "must contain the same cases" in response.json()["detail"]


def test_compare_with_a_missing_run(client: TestClient) -> None:
    baseline = upload(client)["id"]

    response = client.get(f"/runs/{baseline}/compare/{uuid.uuid4()}")

    assert response.status_code == 404


@pytest.mark.parametrize(
    "params",
    [
        {"confidence": 1},
        {"confidence": 0},
        {"n_resamples": 10},
        {"n_resamples": 10**6},
        {"seed": -1},
    ],
)
def test_compare_rejects_bad_parameters(client: TestClient, params: dict[str, float]) -> None:
    run_id = upload(client)["id"]

    response = client.get(f"/runs/{run_id}/compare/{run_id}", params=params)

    assert response.status_code == 422


def test_long_strings_are_cut_short_in_errors(client: TestClient) -> None:
    response = client.post("/runs", json={"name": "x" * 1000, "cases": [{"id": "a", "score": 1}]})

    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == "x" * 100 + "..."
