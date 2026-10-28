"""Request and response bodies."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Big enough for any real eval set, small enough that one request can't exhaust memory.
MAX_CASES = 100_000
MAX_LABELS = 50


class CaseIn(BaseModel):
    id: str = Field(min_length=1, max_length=500)
    score: float = Field(allow_inf_nan=False)
    trace_id: str | None = Field(default=None, pattern="^[0-9a-f]{32}$")


class RunIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    labels: dict[str, str] = Field(default_factory=dict, max_length=MAX_LABELS)
    cases: list[CaseIn] = Field(min_length=1, max_length=MAX_CASES)

    @field_validator("cases")
    @classmethod
    def ids_are_unique(cls, cases: list[CaseIn]) -> list[CaseIn]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for case in cases:
            if case.id in seen:
                duplicates.add(case.id)
            seen.add(case.id)
        if duplicates:
            shown = ", ".join(sorted(duplicates)[:3])
            raise ValueError(f"case ids must be unique, {len(duplicates)} repeated (e.g. {shown})")
        return cases


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    labels: dict[str, str]
    created_at: datetime
    n_cases: int
    mean_score: float


class ComparisonOut(BaseModel):
    baseline_id: uuid.UUID
    candidate_id: uuid.UUID
    baseline_mean: float
    candidate_mean: float
    delta: float
    ci_low: float
    ci_high: float
    confidence: float
    n_cases: int
    n_resamples: int
    verdict: str


class SpanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    service_name: str
    start_time: datetime
    duration_ms: float
    status: str
    status_message: str | None
    attributes: dict[str, Any]


class CaseOut(BaseModel):
    case_id: str
    score: float
    trace_id: str | None
    spans: list[SpanOut]
