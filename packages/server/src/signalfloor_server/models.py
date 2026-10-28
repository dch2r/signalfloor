"""Database tables.

A run is one eval run: a name, some free form labels like the model or prompt version, and one
score per case. Scores are stored per case, not as a file, so two runs can be paired by case id
in the database.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Double, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=func.gen_random_uuid())
    name: Mapped[str] = mapped_column(String(200))
    labels: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
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

    run: Mapped[Run] = relationship(back_populates="cases")
