"""Integration, webhook, workflow and background job schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.domain.enums import (
    Direction,
    IntegrationKind,
    IntegrationStatus,
    JobStatus,
    WebhookStatus,
    WorkflowStatus,
)
from app.schemas.common import ORMModel


class IntegrationOut(ORMModel):
    id: uuid.UUID
    name: str
    kind: IntegrationKind
    status: IntegrationStatus
    is_enabled: bool
    config: dict[str, Any] = Field(default_factory=dict)
    event_filter: list[str] = Field(default_factory=list)
    credential_keys: list[str] = Field(default_factory=list)
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None


class IntegrationCreate(ORMModel):
    name: str = Field(min_length=2, max_length=120)
    kind: IntegrationKind
    config: dict[str, Any] = Field(default_factory=dict)
    event_filter: list[str] = Field(default_factory=list, max_length=50)
    is_enabled: bool = True
    credentials: dict[str, str] = Field(default_factory=dict, max_length=10)


class IntegrationUpdate(ORMModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    config: dict[str, Any] | None = None
    event_filter: list[str] | None = Field(default=None, max_length=50)
    is_enabled: bool | None = None


class CredentialsUpdate(ORMModel):
    credentials: dict[str, str] = Field(min_length=1, max_length=10)


class ConnectionTestOut(ORMModel):
    ok: bool
    status: IntegrationStatus
    detail: str
    latency_ms: float


class WebhookEventOut(ORMModel):
    id: uuid.UUID
    integration_id: uuid.UUID | None = None
    direction: Direction
    event_type: str
    payload: dict[str, Any]
    signature_valid: bool
    status: WebhookStatus
    response_status: int | None = None
    attempts: int
    last_error: str | None = None
    idempotency_key: str
    created_at: datetime
    processed_at: datetime | None = None


class WorkflowTemplateOut(ORMModel):
    key: str
    name: str
    description: str
    trigger_event: str
    file_name: str
    required_parameters: list[str] = Field(default_factory=list)


class WorkflowExecutionOut(ORMModel):
    id: uuid.UUID
    integration_id: uuid.UUID | None = None
    workflow_key: str
    trigger_type: str
    case_id: uuid.UUID | None = None
    status: WorkflowStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    attempts: int
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    created_at: datetime


class TriggerWorkflowRequest(ORMModel):
    case_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class BackgroundJobOut(ORMModel):
    id: uuid.UUID
    task_name: str
    status: JobStatus
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    attempts: int
    max_attempts: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WebhookAck(ORMModel):
    id: uuid.UUID
    status: str
    duplicate: bool = False
