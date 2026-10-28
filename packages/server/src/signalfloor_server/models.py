"""Database tables.

A run is one eval run: a name, some free form labels like the model or prompt version, and one
score per case. Scores are stored per case, not as a file, so two runs can be paired by case id
in the database.

Runs never change after upload, so the case count and mean score are stored on the run itself.
Listing runs then reads one table instead of averaging every case each time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Double,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_created_at", "created_at"),
        # GIN makes "labels contain these pairs" filters use the index.
        Index("ix_runs_labels", "labels", postgresql_using="gin"),
    )
    # Read the server generated id and created_at back in the same INSERT.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(200))
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    n_cases: Mapped[int] = mapped_column(Integer)
    mean_score: Mapped[float] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    cases: Mapped[list[CaseResult]] = relationship(
        back_populates="run", cascade="all, delete-orphan", passive_deletes=True
    )


class CaseResult(Base):
    __tablename__ = "case_results"

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    case_id: Mapped[str] = mapped_column(Text, primary_key=True)
    score: Mapped[float] = mapped_column(Double)
    # Links the case to the trace of the agent run that produced it, if one was recorded.
    trace_id: Mapped[str | None] = mapped_column(String(32))

    run: Mapped[Run] = relationship(back_populates="cases")


class Span(Base):
    """One OpenTelemetry span. Ids are stored as lowercase hex, the form every tool shows."""

    __tablename__ = "spans"
    __table_args__ = (Index("ix_spans_start_time", "start_time"),)

    trace_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    span_id: Mapped[str] = mapped_column(String(16), primary_key=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(Text)
    service_name: Mapped[str] = mapped_column(Text)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Postgres keeps timestamps to the microsecond, so the exact duration is stored separately.
    duration_ns: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(5))
    status_message: Mapped[str | None] = mapped_column(Text)
    attributes: Mapped[dict[str, Any]] = mapped_column(JSONB)

    @property
    def duration_ms(self) -> float:
        return self.duration_ns / 1e6


class Job(Base):
    """A unit of background work, queued in Postgres and run by `signalfloor-server worker`.

    status is queued, running, succeeded or failed. run_after is when the job can next be
    claimed: for a queued job, when it is due, and for a running job, when its worker's lease
    runs out. One column covers both, so a job whose worker died is picked up by the same query
    that picks up new jobs.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        Index(
            "ix_jobs_claimable",
            "run_after",
            postgresql_where=text("status in ('queued', 'running')"),
        ),
    )
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    kind: Mapped[str] = mapped_column(String(50))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(10), server_default="queued")
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, server_default="3")
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
