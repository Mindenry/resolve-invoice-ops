"""Case management schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import Field

from app.domain.enums import (
    CaseStatus,
    CommentVisibility,
    ExceptionStatus,
    ExceptionType,
    Priority,
    Severity,
)
from app.schemas.common import ORMModel


class UserRef(ORMModel):
    id: uuid.UUID
    full_name: str
    email: str
    avatar_color: str | None = None


class CaseLinkOut(ORMModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    label: str | None = None
    created_at: datetime


class CaseExceptionOut(ORMModel):
    id: uuid.UUID
    exception_type: ExceptionType
    severity: Severity
    status: ExceptionStatus
    title: str
    rule_code: str
    rule_version: int
    detection_count: int
    first_detected_at: datetime
    last_detected_at: datetime


class CaseCommentOut(ORMModel):
    id: uuid.UUID
    author_id: uuid.UUID | None = None
    author_name: str | None = None
    body: str
    visibility: CommentVisibility
    created_at: datetime
    edited_at: datetime | None = None


class CaseActivityOut(ORMModel):
    id: uuid.UUID
    actor_id: uuid.UUID | None = None
    actor_name: str | None = None
    activity_type: str
    summary: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class TimelineItem(ORMModel):
    kind: Literal["ACTIVITY", "COMMENT"]
    id: uuid.UUID
    actor_name: str | None = None
    summary: str
    detail: str | None = None
    visibility: CommentVisibility | None = None
    created_at: datetime


class CaseSummary(ORMModel):
    id: uuid.UUID
    case_number: str
    title: str
    status: CaseStatus
    priority: Priority
    severity: Severity
    assigned_user: UserRef | None = None
    due_at: datetime | None = None
    sla_hours: int
    sla_breached: bool
    tags: list[str]
    exception_count: int = 0
    is_demo: bool
    created_at: datetime
    last_activity_at: datetime


class CaseDetail(CaseSummary):
    description: str
    resolution_summary: str | None = None
    resolved_at: datetime | None = None
    closed_at: datetime | None = None
    first_response_at: datetime | None = None
    created_by: UserRef | None = None
    merged_into_case_id: uuid.UUID | None = None
    links: list[CaseLinkOut] = Field(default_factory=list)
    exceptions: list[CaseExceptionOut] = Field(default_factory=list)
    comments: list[CaseCommentOut] = Field(default_factory=list)
    activities: list[CaseActivityOut] = Field(default_factory=list)


class CaseCreate(ORMModel):
    title: str = Field(min_length=3, max_length=250)
    description: str = Field(default="", max_length=20_000)
    priority: Priority = Priority.MEDIUM
    severity: Severity | None = None
    assigned_user_id: uuid.UUID | None = None
    tags: list[str] = Field(default_factory=list, max_length=20)
    invoice_id: uuid.UUID | None = None
    exception_ids: list[uuid.UUID] = Field(default_factory=list, max_length=50)
    sla_hours: int | None = Field(default=None, ge=1, le=720)


class CaseUpdate(ORMModel):
    title: str | None = Field(default=None, min_length=3, max_length=250)
    description: str | None = Field(default=None, max_length=20_000)
    priority: Priority | None = None
    severity: Severity | None = None
    tags: list[str] | None = Field(default=None, max_length=20)
    due_at: datetime | None = None
    sla_hours: int | None = Field(default=None, ge=1, le=720)


class CaseTransitionRequest(ORMModel):
    status: CaseStatus
    note: str | None = Field(default=None, max_length=2000)
    resolution_summary: str | None = Field(default=None, max_length=8000)


class CaseAssignRequest(ORMModel):
    user_id: uuid.UUID | None
    reason: str | None = Field(default=None, max_length=255)


class CaseCommentCreate(ORMModel):
    body: str = Field(min_length=1, max_length=8000)
    visibility: CommentVisibility = CommentVisibility.INTERNAL


class CaseEscalateRequest(ORMModel):
    reason: str = Field(min_length=3, max_length=1000)
    priority: Priority = Priority.URGENT


class CaseMergeRequest(ORMModel):
    source_case_id: uuid.UUID
    note: str | None = Field(default=None, max_length=1000)


class CaseResolveRequest(ORMModel):
    resolution_summary: str = Field(min_length=3, max_length=8000)
    close: bool = False


class BulkAssignRequest(ORMModel):
    case_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    user_id: uuid.UUID | None
