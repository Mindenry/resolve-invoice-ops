"""AI evaluation schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.domain.enums import JobStatus
from app.schemas.common import ORMModel


class EvaluationSampleIn(ORMModel):
    sample_key: str = Field(min_length=1, max_length=80)
    case_context: dict[str, Any] = Field(default_factory=dict)
    expected_exception_types: list[str] = Field(default_factory=list, max_length=10)
    expected_root_cause: str = Field(default="", max_length=4000)
    expected_evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    expected_recommendations: list[str] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=2000)


class EvaluationSampleOut(EvaluationSampleIn):
    id: uuid.UUID


class DatasetCreate(ORMModel):
    name: str = Field(min_length=2, max_length=120)
    description: str = Field(default="", max_length=4000)
    version: str = Field(default="1.0", max_length=20)
    is_synthetic: bool = True
    samples: list[EvaluationSampleIn] = Field(min_length=1, max_length=200)


class DatasetOut(ORMModel):
    id: uuid.UUID
    name: str
    description: str
    version: str
    is_synthetic: bool
    sample_count: int
    created_at: datetime


class DatasetDetail(DatasetOut):
    samples: list[EvaluationSampleOut] = Field(default_factory=list)


class EvaluationRunCreate(ORMModel):
    dataset_id: uuid.UUID
    name: str = Field(min_length=2, max_length=160)
    prompt_version: str = Field(default="investigation.v1", max_length=40)
    retrieval_config: dict[str, Any] = Field(default_factory=dict)


class EvaluationRunOut(ORMModel):
    id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str | None = None
    name: str
    provider: str
    model: str | None = None
    prompt_version: str
    retrieval_config: dict[str, Any] = Field(default_factory=dict)
    status: JobStatus
    metrics: dict[str, Any] = Field(default_factory=dict)
    sample_total: int
    sample_completed: int
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class EvaluationResultOut(ORMModel):
    id: uuid.UUID
    sample_key: str
    predicted: dict[str, Any] = Field(default_factory=dict)
    expected: dict[str, Any] = Field(default_factory=dict)
    scores: dict[str, Any] = Field(default_factory=dict)
    latency_ms: int | None = None
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    error: str | None = None


class EvaluationRunDetail(EvaluationRunOut):
    results: list[EvaluationResultOut] = Field(default_factory=list)


class ComparisonRow(ORMModel):
    run_id: uuid.UUID
    name: str
    provider: str
    model: str | None = None
    prompt_version: str
    status: JobStatus
    metrics: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
