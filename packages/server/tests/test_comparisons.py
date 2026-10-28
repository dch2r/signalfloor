import asyncio
import threading
import time
import uuid
from typing import Any

import anyio
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from signalfloor.compare import paired_bootstrap
from signalfloor_server import comparisons


@pytest.fixture
def bootstraps(monkeypatch: pytest.MonkeyPatch) -> list[object]:
    """Count real bootstrap calls."""
    calls: list[object] = []

    def counting(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs.get("seed"))
        return paired_bootstrap(*args, **kwargs)

    monkeypatch.setattr(comparisons, "paired_bootstrap", counting)
    return calls


def two_runs(client: TestClient) -> tuple[str, str]:
    ids = []
    for name, scores in (("base", [1.0, 0.0, 1.0, 1.0]), ("cand", [1.0, 1.0, 0.0, 0.0])):
        cases = [{"id": f"q{i}", "score": s} for i, s in enumerate(scores)]
        ids.append(client.post("/runs", json={"name": name, "cases": cases}).json()["id"])
    return ids[0], ids[1]


def test_seeded_comparisons_are_cached(client: TestClient, bootstraps: list[object]) -> None:
    baseline, candidate = two_runs(client)
    url = f"/runs/{baseline}/compare/{candidate}"

    first = client.get(url, params={"seed": 0}).json()
    second = client.get(url, params={"seed": 0}).json()
    client.get(url, params={"seed": 1})

    assert first == second
    # The repeat was served from the cache. Another seed is a different result, so it ran.
    assert bootstraps == [0, 1]


def test_unseeded_comparisons_are_always_fresh(
    client: TestClient, bootstraps: list[object]
) -> None:
    baseline, candidate = two_runs(client)

    client.get(f"/runs/{baseline}/compare/{candidate}")
    client.get(f"/runs/{baseline}/compare/{candidate}")

    assert bootstraps == [None, None]


def test_a_deleted_run_is_not_served_from_the_cache(client: TestClient) -> None:
    baseline, candidate = two_runs(client)
    url = f"/runs/{baseline}/compare/{candidate}"
    assert client.get(url, params={"seed": 0}).status_code == 200

    client.delete(f"/runs/{candidate}")

    assert client.get(url, params={"seed": 0}).status_code == 404


def test_the_cache_forgets_the_oldest_entry(
    client: TestClient, bootstraps: list[object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparisons, "CACHE_SIZE", 2)
    baseline, candidate = two_runs(client)
    url = f"/runs/{baseline}/compare/{candidate}"

    for seed in (0, 1, 0, 2, 1):
        client.get(url, params={"seed": seed})

    # 0 and 1 are computed, 0 is a hit and becomes the newest, 2 pushes out 1, so 1 is computed
    # again.
    assert bootstraps == [0, 1, 2, 1]


def test_only_a_few_bootstraps_run_at_once(
    client: TestClient, clean_db: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(comparisons, "_bootstraps", anyio.CapacityLimiter(2))
    running = 0
    most = 0
    lock = threading.Lock()

    def slow(*args: Any, **kwargs: Any) -> Any:
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return paired_bootstrap(*args, **kwargs)

    monkeypatch.setattr(comparisons, "paired_bootstrap", slow)
    baseline, candidate = two_runs(client)

    async def scenario() -> None:
        engine = create_async_engine(clean_db)
        sessions = async_sessionmaker(engine, expire_on_commit=False)

        async def one(seed: int) -> None:
            async with sessions() as session:
                await comparisons.compare(
                    session,
                    uuid.UUID(baseline),
                    uuid.UUID(candidate),
                    confidence=0.95,
                    n_resamples=100,
                    seed=seed,
                )

        await asyncio.gather(*(one(seed) for seed in range(6)))
        await engine.dispose()

    asyncio.run(scenario())

    assert most == 2
