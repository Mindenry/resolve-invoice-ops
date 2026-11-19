"""Automation, integration, notification and background job models."""

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

from app.db.base import Base, OrgScopedMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import (
    Direction,
    IntegrationKind,
    IntegrationStatus,
    JobStatus,
    NotificationChannel,
    NotificationStatus,
    NotificationType,
    WebhookStatus,
    WorkflowStatus,
    enum_type,
)


class Integration(UUIDPrimaryKeyMixin, TimestampMixin, OrgScopedMixin, Base):
    __tablename__ = "integrations"
    __table_args__ = (UniqueConstraint("org_id", "name", name="uq_integration_org_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[IntegrationKind] = mapped_column(enum_type(IntegrationKind, "integration_kind"), nullable=False)
    status: Mapped[IntegrationStatus] = mapped_column(
        enum_type(IntegrationStatus, "integration_status"),
        default=IntegrationStatus.UNTESTED,
        nullable=False,
    )
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    event_filter: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )


class IntegrationCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Credentials are encrypted at rest; plaintext is never returned by the API."""

    __tablename__ = "integration_credentials"
    __table_args__ = (UniqueConstraint("integration_id", "key", name="uq_integration_credential_key"),)

    integration_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WebhookEvent(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint("org_id", "idempotency_key", name="uq_webhook_org_idempotency"),
        Index("ix_webhook_events_org_created", "org_id", "created_at"),
    )

    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL"), index=True
    )
    direction: Mapped[Direction] = mapped_column(enum_type(Direction, "webhook_direction"), nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    headers: Mapped[dict[str, str]] = mapped_column(default=dict, nullable=False)
    signature_valid: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[WebhookStatus] = mapped_column(
        enum_type(WebhookStatus, "webhook_status"), default=WebhookStatus.RECEIVED, nullable=False
    )
    response_status: Mapped[int | None] = mapped_column(Integer)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str] = mapped_column(String(120), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkflowExecution(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    __tablename__ = "workflow_executions"
    __table_args__ = (Index("ix_workflow_exec_org_status", "org_id", "status"),)

    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("integrations.id", ondelete="SET NULL"), index=True
    )
    workflow_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    trigger_type: Mapped[str] = mapped_column(String(40), default="EVENT", nullable=False)
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("cases.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[WorkflowStatus] = mapped_column(
        enum_type(WorkflowStatus, "workflow_status"), default=WorkflowStatus.QUEUED, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column()
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
    idempotency_key: Mapped[str | None] = mapped_column(String(120), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class Notification(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    __tablename__ = "notifications"
    __table_args__ = (Index("ix_notifications_user_created", "user_id", "created_at"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[NotificationType] = mapped_column(
        enum_type(NotificationType, "notification_type"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, default="", nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    channel: Mapped[NotificationChannel] = mapped_column(
        enum_type(NotificationChannel, "notification_channel"),
        default=NotificationChannel.IN_APP,
        nullable=False,
    )
    status: Mapped[NotificationStatus] = mapped_column(
        enum_type(NotificationStatus, "notification_status"),
        default=NotificationStatus.PENDING,
        nullable=False,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    email_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "notification_preferences"
    __table_args__ = (UniqueConstraint("user_id", "event_type", name="uq_notification_pref"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    in_app: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    email: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class BackgroundJob(UUIDPrimaryKeyMixin, OrgScopedMixin, Base):
    __tablename__ = "background_jobs"
    __table_args__ = (Index("ix_background_jobs_org_status", "org_id", "status"),)

    task_name: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    status: Mapped[JobStatus] = mapped_column(
        enum_type(JobStatus, "job_status"), default=JobStatus.QUEUED, nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3, nullable=False)
    celery_task_id: Mapped[str | None] = mapped_column(String(80))
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
