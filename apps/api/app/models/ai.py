"""AI investigation, resolution, approval and usage models."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
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
from app.domain.enums import (
    ActionType,
    ApprovalStatus,
    InvestigationSourceType,
    InvestigationStatus,
    ResolutionStatus,
    RiskLevel,
    enum_type,
)


class Investigation(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "investigations"
    __table_args__ = (Index("ix_investigations_org_case", "org_id", "case_id", "created_at"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[InvestigationStatus] = mapped_column(
        enum_type(InvestigationStatus, "investigation_status"),
        default=InvestigationStatus.QUEUED,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(40), default="none", nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40), default="investigation.v1", nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    root_cause: Mapped[str | None] = mapped_column(Text)
    root_cause_hypotheses: Mapped[list[dict[str, Any]]] = mapped_column(default=list, nullable=False)
    risk_level: Mapped[RiskLevel | None] = mapped_column(enum_type(RiskLevel, "investigation_risk"))
    confidence: Mapped[float | None] = mapped_column(Float)
    confidence_basis: Mapped[str | None] = mapped_column(String(400))
    requires_human_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    missing_information: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    limitations: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    required_actions: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    suggested_resolutions: Mapped[list[dict[str, Any]]] = mapped_column(default=list, nullable=False)
    raw_output: Mapped[dict[str, Any] | None] = mapped_column()
    context_summary: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    error_code: Mapped[str | None] = mapped_column(String(60))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InvestigationEvidence(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "investigation_evidence"

    investigation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type: Mapped[InvestigationSourceType] = mapped_column(
        enum_type(InvestigationSourceType, "evidence_source_type"), nullable=False
    )
    source_id: Mapped[str | None] = mapped_column(String(64))
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL")
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    field_name: Mapped[str | None] = mapped_column(String(60))
    quote: Mapped[str] = mapped_column(Text, nullable=False)
    relationship: Mapped[str | None] = mapped_column(String(400))
    is_contradicting: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_validated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    validation_error: Mapped[str | None] = mapped_column(String(400))


class Resolution(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "resolutions"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_resolution_idempotency"),
        Index("ix_resolutions_org_case", "org_id", "case_id"),
    )

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    investigation_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("investigations.id", ondelete="SET NULL")
    )
    action_type: Mapped[ActionType] = mapped_column(enum_type(ActionType, "action_type"), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    supporting_evidence: Mapped[list[dict[str, Any]]] = mapped_column(default=list, nullable=False)
    risk_level: Mapped[RiskLevel] = mapped_column(enum_type(RiskLevel, "resolution_risk"), nullable=False)
    expected_outcome: Mapped[str | None] = mapped_column(Text)
    required_permissions: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[ResolutionStatus] = mapped_column(
        enum_type(ResolutionStatus, "resolution_status"),
        default=ResolutionStatus.PROPOSED,
        nullable=False,
    )
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    ai_model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    validation_errors: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    execution_result: Mapped[dict[str, Any] | None] = mapped_column()
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    error: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class ResolutionExecution(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "resolution_executions"

    resolution_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("resolutions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    result: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApprovalRequest(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (Index("ix_approvals_org_status", "org_id", "status"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resolution_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("resolutions.id", ondelete="SET NULL"), index=True
    )
    action_type: Mapped[ActionType] = mapped_column(enum_type(ActionType, "approval_action_type"), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    requester_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False, index=True
    )
    approver_role: Mapped[str | None] = mapped_column(String(40))
    assigned_approver_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    risk_level: Mapped[RiskLevel] = mapped_column(enum_type(RiskLevel, "approval_risk"), nullable=False)
    status: Mapped[ApprovalStatus] = mapped_column(
        enum_type(ApprovalStatus, "approval_status"), default=ApprovalStatus.PENDING, nullable=False
    )
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(default=list, nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class ApprovalDecision(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "approval_decisions"

    request_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("approval_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    decision: Mapped[str] = mapped_column(String(20), nullable=False)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIUsageEvent(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "ai_usage_events"
    __table_args__ = (Index("ix_ai_usage_org_created", "org_id", "created_at"),)

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="SET NULL"), index=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    purpose: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(40), nullable=False)
    model: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    error: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
