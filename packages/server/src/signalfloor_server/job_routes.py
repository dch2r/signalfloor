"""Start background jobs and check on them."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Response

from signalfloor_server import jobs
from signalfloor_server.db import Session
from signalfloor_server.models import Job, Run
from signalfloor_server.schemas import CompareJobIn, JobOut

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/compare", status_code=202)
async def start_compare(body: CompareJobIn, session: Session, response: Response) -> JobOut:
    """Queue a comparison. Poll GET /jobs/{id} until its status is succeeded or failed."""
    for run_id in (body.baseline_id, body.candidate_id):
        if await session.get(Run, run_id) is None:
            raise HTTPException(404, f"run {run_id} not found")
    job = await jobs.enqueue(session, "compare", body.model_dump(mode="json"))
    await session.commit()
    response.headers["location"] = f"/jobs/{job.id}"
    return JobOut.model_validate(job)


@router.get("/{job_id}")
async def get_job(job_id: uuid.UUID, session: Session) -> JobOut:
    job = await session.get(Job, job_id)
    if job is None:
        raise HTTPException(404, f"job {job_id} not found")
    return JobOut.model_validate(job)
