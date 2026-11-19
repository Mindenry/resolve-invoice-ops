"""Exception detection, case management and investigation linkage models."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import (
    CaseStatus,
    CommentVisibility,
    ExceptionStatus,
    ExceptionType,
    Priority,
    Severity,
    enum_type,
)


class ExceptionRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "exception_rules"
    __table_args__ = (
        UniqueConstraint("org_id", "code", name="uq_exception_rule_org_code"),
        Index("ix_exception_rules_org_enabled", "org_id", "is_enabled"),
    )

    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    exception_type: Mapped[ExceptionType] = mapped_column(
        enum_type(ExceptionType, "rule_exception_type"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(enum_type(Severity, "rule_severity"), nullable=False)
    applies_to: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class ExceptionRuleVersion(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "exception_rule_versions"
    __table_args__ = (UniqueConstraint("rule_id", "version", name="uq_exception_rule_version"),)

    rule_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exception_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    conditions: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    test_cases: Mapped[list[dict[str, Any]]] = mapped_column(default=list, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    change_note: Mapped[str | None] = mapped_column(String(255))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Case(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OrgScopedMixin, Base):
    __tablename__ = "cases"
    __table_args__ = (
        UniqueConstraint("org_id", "case_number", name="uq_case_org_number"),
        Index("ix_cases_org_status", "org_id", "status"),
        Index("ix_cases_org_priority", "org_id", "priority"),
        Index("ix_cases_assignee", "assigned_user_id", "status"),
        Index("ix_cases_due", "org_id", "due_at"),
    )

    case_number: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    status: Mapped[CaseStatus] = mapped_column(
        enum_type(CaseStatus, "case_status"), default=CaseStatus.OPEN, nullable=False
    )
    priority: Mapped[Priority] = mapped_column(
        enum_type(Priority, "case_priority"), default=Priority.MEDIUM, nullable=False
    )
    severity: Mapped[Severity] = mapped_column(
        enum_type(Severity, "case_severity"), default=Severity.MEDIUM, nullable=False
    )
    assigned_user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    sla_hours: Mapped[int] = mapped_column(Integer, default=48, nullable=False)
    sla_breached: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_summary: Mapped[str | None] = mapped_column(Text)
    first_response_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    merged_into_case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL")
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class ExceptionRecord(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "exceptions"
    __table_args__ = (
        UniqueConstraint("org_id", "fingerprint", name="uq_exception_org_fingerprint"),
        Index("ix_exceptions_org_status", "org_id", "status"),
        Index("ix_exceptions_org_type", "org_id", "exception_type"),
        Index("ix_exceptions_entity", "entity_type", "entity_id"),
        Index("ix_exceptions_case", "case_id"),
    )

    exception_type: Mapped[ExceptionType] = mapped_column(
        enum_type(ExceptionType, "exception_type"), nullable=False
    )
    severity: Mapped[Severity] = mapped_column(enum_type(Severity, "exception_severity"), nullable=False)
    status: Mapped[ExceptionStatus] = mapped_column(
        enum_type(ExceptionStatus, "exception_status"), default=ExceptionStatus.OPEN, nullable=False
    )
    rule_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("exception_rules.id", ondelete="SET NULL")
    )
    rule_code: Mapped[str] = mapped_column(String(60), nullable=False)
    rule_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(250), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    first_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    detection_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), index=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    resolution_note: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class CaseLink(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "case_links"
    __table_args__ = (
        UniqueConstraint("case_id", "entity_type", "entity_id", name="uq_case_link_entity"),
        Index("ix_case_links_org_entity", "org_id", "entity_type", "entity_id"),
    )

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    label: Mapped[str | None] = mapped_column(String(250))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CaseAssignment(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "case_assignments"

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_to_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=False, index=True
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[str | None] = mapped_column(String(255))
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseComment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "case_comments"
    __table_args__ = (Index("ix_case_comments_case_created", "case_id", "created_at"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[CommentVisibility] = mapped_column(
        enum_type(CommentVisibility, "comment_visibility"),
        default=CommentVisibility.INTERNAL,
        nullable=False,
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseActivity(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "case_activities"
    __table_args__ = (Index("ix_case_activities_case_created", "case_id", "created_at"),)

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    activity_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    summary: Mapped[str] = mapped_column(String(400), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class SavedFilter(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "saved_filters"
    __table_args__ = (UniqueConstraint("user_id", "resource", "name", name="uq_saved_filter_name"),)

    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource: Mapped[str] = mapped_column(String(40), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    query: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
