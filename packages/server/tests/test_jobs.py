import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from signalfloor_server import jobs
from signalfloor_server.models import Job, Span
from signalfloor_server.retention import prune_spans

T = TypeVar("T")
Sessions = async_sessionmaker[AsyncSession]


def with_sessions(database_url: str, fn: Callable[[Sessions], Awaitable[T]]) -> T:
    async def go() -> T:
        engine = create_async_engine(database_url)
        try:
            return await fn(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(go())


async def add_job(sessions: Sessions, kind: str = "test", **payload: Any) -> uuid.UUID:
    async with sessions() as session:
        job = await jobs.enqueue(session, kind, payload, max_attempts=payload.pop("tries", 3))
        await session.commit()
        return job.id


async def get(sessions: Sessions, job_id: uuid.UUID) -> Job:
    async with sessions() as session:
        job = await session.get(Job, job_id)
        assert job is not None
        return job


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Register a "test" job kind that records its payload and can be told to fail."""
    seen: list[dict[str, Any]] = []

    async def handler(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        await asyncio.sleep(payload.get("sleep", 0))
        if len(seen) <= payload.get("fail_times", 0):
            raise RuntimeError("boom")
        if payload.get("permanent"):
            raise jobs.PermanentError("never going to work")
        return {"n": payload.get("n")}

    monkeypatch.setitem(jobs.HANDLERS, "test", handler)
    monkeypatch.setattr(jobs, "BACKOFF_SECONDS", 0.0)
    return seen


def upload(client: TestClient, scores: list[float]) -> str:
    cases = [{"id": f"q{i}", "score": s} for i, s in enumerate(scores)]
    run_id: str = client.post("/runs", json={"name": "r", "cases": cases}).json()["id"]
    return run_id


def test_compare_job_end_to_end(client: TestClient, clean_db: str) -> None:
    baseline = upload(client, [1.0] * 50 + [0.0] * 50)
    candidate = upload(client, [1.0] * 20 + [0.0] * 80)

    started = client.post(
        "/jobs/compare",
        json={"baseline_id": baseline, "candidate_id": candidate, "seed": 0, "n_resamples": 500},
    )
    assert started.status_code == 202
    job = started.json()
    assert started.headers["location"] == f"/jobs/{job['id']}"
    assert (job["kind"], job["status"], job["attempts"], job["result"]) == (
        "compare",
        "queued",
        0,
        None,
    )

    assert with_sessions(clean_db, jobs.run_one) is True

    done = client.get(f"/jobs/{job['id']}").json()
    direct = client.get(
        f"/runs/{baseline}/compare/{candidate}", params={"seed": 0, "n_resamples": 500}
    ).json()
    assert done["status"] == "succeeded"
    assert done["attempts"] == 1
    assert done["result"] == direct
    assert done["started_at"] and done["finished_at"]


def test_compare_job_with_shared_cases_only(client: TestClient, clean_db: str) -> None:
    baseline = upload(client, [1.0, 0.0])
    candidate = upload(client, [1.0, 1.0, 0.0])
    body = {"baseline_id": baseline, "candidate_id": candidate, "n_resamples": 200}
    strict = client.post("/jobs/compare", json=body).json()["id"]
    shared = client.post("/jobs/compare", json={**body, "shared_only": True}).json()["id"]

    while with_sessions(clean_db, jobs.run_one):
        pass

    assert client.get(f"/jobs/{strict}").json()["status"] == "failed"
    done = client.get(f"/jobs/{shared}").json()
    assert done["status"] == "succeeded"
    assert done["result"]["n_cases"] == 2


def test_compare_job_for_a_missing_run(client: TestClient) -> None:
    run_id = upload(client, [1.0, 0.0])

    response = client.post(
        "/jobs/compare", json={"baseline_id": run_id, "candidate_id": str(uuid.uuid4())}
    )

    assert response.status_code == 404


def test_compare_job_allows_more_resamples_than_the_endpoint(client: TestClient) -> None:
    run_id = upload(client, [1.0, 0.0])
    body = {"baseline_id": run_id, "candidate_id": run_id}

    assert client.post("/jobs/compare", json={**body, "n_resamples": 1_000_000}).status_code == 202
    assert client.post("/jobs/compare", json={**body, "n_resamples": 1_000_001}).status_code == 422


def test_missing_job(client: TestClient) -> None:
    assert client.get(f"/jobs/{uuid.uuid4()}").status_code == 404


def test_run_deleted_before_the_job_ran_fails_without_retrying(
    client: TestClient, clean_db: str
) -> None:
    run_id = upload(client, [1.0, 0.0])
    job_id = client.post(
        "/jobs/compare", json={"baseline_id": run_id, "candidate_id": run_id}
    ).json()["id"]
    client.delete(f"/runs/{run_id}")

    with_sessions(clean_db, jobs.run_one)

    job = client.get(f"/jobs/{job_id}").json()
    assert (job["status"], job["attempts"]) == ("failed", 1)
    assert "not found" in job["error"]


def test_concurrent_workers_never_take_the_same_job(
    clean_db: str, calls: list[dict[str, Any]]
) -> None:
    async def scenario(sessions: Sessions) -> list[Job]:
        ids = [await add_job(sessions, n=i, sleep=0.01) for i in range(20)]

        async def worker() -> None:
            while await jobs.run_one(sessions):
                pass

        await asyncio.gather(*(worker() for _ in range(4)))
        return [await get(sessions, i) for i in ids]

    done = with_sessions(clean_db, scenario)

    assert sorted(c["n"] for c in calls) == list(range(20))
    assert {j.status for j in done} == {"succeeded"}
    assert {j.attempts for j in done} == {1}


def test_failed_job_is_retried(clean_db: str, calls: list[dict[str, Any]]) -> None:
    async def scenario(sessions: Sessions) -> tuple[Job, Job]:
        job_id = await add_job(sessions, fail_times=1, n=7)
        await jobs.run_one(sessions)
        after_failure = await get(sessions, job_id)
        await jobs.run_one(sessions)
        return after_failure, await get(sessions, job_id)

    after_failure, done = with_sessions(clean_db, scenario)

    assert after_failure.status == "queued"
    assert after_failure.error and "RuntimeError: boom" in after_failure.error
    assert after_failure.finished_at is None
    assert (done.status, done.attempts, done.result, done.error) == ("succeeded", 2, {"n": 7}, None)


def test_retries_back_off(
    clean_db: str, calls: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(jobs, "BACKOFF_SECONDS", 60.0)

    async def scenario(sessions: Sessions) -> bool:
        await add_job(sessions, fail_times=1)
        await jobs.run_one(sessions)
        return await jobs.run_one(sessions)

    assert with_sessions(clean_db, scenario) is False


def test_job_fails_after_its_last_attempt(clean_db: str, calls: list[dict[str, Any]]) -> None:
    async def scenario(sessions: Sessions) -> Job:
        job_id = await add_job(sessions, fail_times=5, tries=2)
        while await jobs.run_one(sessions):
            pass
        return await get(sessions, job_id)

    job = with_sessions(clean_db, scenario)

    assert (job.status, job.attempts) == ("failed", 2)
    assert job.error and "boom" in job.error
    assert len(calls) == 2


def test_permanent_errors_are_not_retried(clean_db: str, calls: list[dict[str, Any]]) -> None:
    async def scenario(sessions: Sessions) -> Job:
        job_id = await add_job(sessions, permanent=True)
        while await jobs.run_one(sessions):
            pass
        return await get(sessions, job_id)

    job = with_sessions(clean_db, scenario)

    assert (job.status, job.attempts, job.error) == ("failed", 1, "never going to work")


def test_a_dead_workers_job_is_picked_up_and_its_late_result_dropped(
    clean_db: str, calls: list[dict[str, Any]], caplog: pytest.LogCaptureFixture
) -> None:
    async def scenario(sessions: Sessions) -> Job:
        job_id = await add_job(sessions, n=1)
        async with sessions() as session:
            # Worker A claims the job with a lease that has already run out, then stalls.
            stale = await jobs.claim(session, lease=timedelta(0))
        assert stale is not None
        # Worker B picks it up and finishes it.
        assert await jobs.run_one(sessions)
        # Worker A wakes up and tries to record its own result.
        await jobs._finish(sessions, stale, "failed", error="too late")
        return await get(sessions, job_id)

    job = with_sessions(clean_db, scenario)

    assert (job.status, job.attempts, job.result) == ("succeeded", 2, {"n": 1})
    assert "lost the lease" in caplog.text


def test_job_whose_workers_keep_dying_is_given_up(
    clean_db: str, calls: list[dict[str, Any]]
) -> None:
    async def scenario(sessions: Sessions) -> Job:
        job_id = await add_job(sessions, tries=1)
        async with sessions() as session:
            await jobs.claim(session, lease=timedelta(0))
        await jobs.run_one(sessions)
        return await get(sessions, job_id)

    job = with_sessions(clean_db, scenario)

    assert (job.status, job.error) == ("failed", "gave up after 1 attempts")
    assert calls == []


def test_unknown_kind(clean_db: str) -> None:
    async def scenario(sessions: Sessions) -> Job:
        async with sessions() as session:
            job = Job(kind="removed_kind", payload={})
            session.add(job)
            await session.commit()
        await jobs.run_one(sessions)
        return await get(sessions, job.id)

    job = with_sessions(clean_db, scenario)

    assert (job.status, job.error) == ("failed", "unknown job kind 'removed_kind'")


def test_enqueue_rejects_unknown_kinds(clean_db: str) -> None:
    async def scenario(sessions: Sessions) -> None:
        await add_job(sessions, kind="nope")

    with pytest.raises(ValueError, match="unknown job kind 'nope'"):
        with_sessions(clean_db, scenario)


def test_work_loop_runs_jobs_until_stopped(clean_db: str, calls: list[dict[str, Any]]) -> None:
    async def scenario(sessions: Sessions) -> list[str]:
        stop = asyncio.Event()
        loop = asyncio.create_task(jobs.work(sessions, stop, poll_interval=0.01))
        ids = [await add_job(sessions, n=i) for i in range(3)]
        for _ in range(500):
            statuses = [(await get(sessions, i)).status for i in ids]
            if set(statuses) == {"succeeded"}:
                break
            await asyncio.sleep(0.01)
        stop.set()
        await asyncio.wait_for(loop, 5)
        return statuses

    assert with_sessions(clean_db, scenario) == ["succeeded"] * 3


def test_prune_spans_deletes_only_old_spans_in_batches(clean_db: str) -> None:
    now = datetime.now(UTC)

    def span(i: int, age: timedelta) -> dict[str, Any]:
        return {
            "trace_id": f"{i:032x}",
            "span_id": f"{i:016x}",
            "name": "s",
            "service_name": "test",
            "start_time": now - age,
            "duration_ns": 1,
            "status": "unset",
            "attributes": {},
        }

    async def scenario(sessions: Sessions) -> tuple[int, int]:
        async with sessions() as session:
            old = [span(i, timedelta(days=40)) for i in range(5)]
            new = [span(i + 100, timedelta(days=1)) for i in range(2)]
            await session.execute(insert(Span), old + new)
            await session.commit()
            deleted = await prune_spans(session, timedelta(days=30), batch_size=2)
            left = await session.scalar(select(func.count()).select_from(Span))
            return deleted, left or 0

    assert with_sessions(clean_db, scenario) == (5, 2)


def test_worker_waits_for_the_database_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from sqlalchemy.exc import ProgrammingError

    attempts: list[str] = []
    stop = asyncio.Event()

    async def flaky_run_one(sessions: object, lease: object) -> bool:
        attempts.append("try")
        if len(attempts) == 1:
            raise OSError("connection refused")
        if len(attempts) == 2:
            raise ProgrammingError("select", {}, Exception('relation "jobs" does not exist'))
        stop.set()
        return True

    monkeypatch.setattr(jobs, "run_one", flaky_run_one)

    async def scenario() -> None:
        await asyncio.wait_for(jobs.work(None, stop, poll_interval=0.001), 5)  # type: ignore[arg-type]

    asyncio.run(scenario())

    assert len(attempts) == 3
    assert caplog.text.count("database not available") == 2
    assert "OSError" in caplog.text and "ProgrammingError" in caplog.text
