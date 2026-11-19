"""AI evaluation dataset, run and result models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import JobStatus, enum_type


class EvaluationDataset(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "evaluation_datasets"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_eval_dataset_org_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="1.0", nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(default=True, nullable=False)
    sample_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class EvaluationSample(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "evaluation_samples"
    __table_args__ = (UniqueConstraint("dataset_id", "sample_key", name="uq_eval_sample_key"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_key: Mapped[str] = mapped_column(String(80), nullable=False)
    case_context: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    expected_exception_types: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    expected_root_cause: Mapped[str] = mapped_column(Text, default="", nullable=False)
    expected_evidence: Mapped[list[dict[str, Any]]] = mapped_column(default=list, nullable=False)
    expected_recommendations: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class EvaluationRun(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (Index("ix_eval_runs_org_status", "org_id", "status"),)

    dataset_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_datasets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40), nullable=False)
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "eval_run_status"), default=JobStatus.QUEUED, nullable=False
    )
    metrics: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    sample_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sample_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class EvaluationResult(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "evaluation_results"
    __table_args__ = (UniqueConstraint("run_id", "sample_id", name="uq_eval_result_sample"),)

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sample_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_samples.id", ondelete="CASCADE"), nullable=False, index=True
    )
    predicted: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    expected: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EvaluationMetricSummary(UUIDPrimaryKeyMixin, Base):
    """Per-run aggregate snapshot for fast comparison in the UI."""

    __tablename__ = "evaluation_metric_summaries"

    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("evaluation_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    metric: Mapped[str] = mapped_column(String(60), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
