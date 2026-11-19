"""Exception schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.domain.enums import (
    CaseStatus,
    ExceptionStatus,
    ExceptionType,
    Priority,
    Severity,
)
from app.schemas.common import ORMModel


class ExceptionOut(ORMModel):
    id: uuid.UUID
    exception_type: ExceptionType
    severity: Severity
    status: ExceptionStatus
    title: str
    description: str
    rule_code: str
    rule_version: int
    entity_type: str
    entity_id: uuid.UUID
    case_id: uuid.UUID | None = None
    case_number: str | None = None
    case_status: CaseStatus | None = None
    detection_count: int
    first_detected_at: datetime
    last_detected_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)
    is_demo: bool


class ExceptionDetail(ExceptionOut):
    rule_name: str | None = None
    related: dict[str, Any] = Field(default_factory=dict)


class ExceptionStatusUpdate(ORMModel):
    status: ExceptionStatus
    note: str | None = Field(default=None, max_length=2000)


class DetectionRequest(ORMModel):
    invoice_id: uuid.UUID | None = None
    include_invoices: bool = False
    include_vendors: bool = False
    include_integrations: bool = False
    create_cases: bool = True
    limit: int = Field(default=200, ge=1, le=1000)


class DetectionResult(ORMModel):
    scanned_invoices: int = 0
    scanned_vendors: int = 0
    created_exceptions: int = 0
    updated_exceptions: int = 0
    opened_cases: int = 0
    exception_ids: list[uuid.UUID] = Field(default_factory=list)
    rule_errors: list[dict[str, str]] = Field(default_factory=list)


class RuleVersionOut(ORMModel):
    id: uuid.UUID
    version: int
    config: dict[str, Any]
    conditions: dict[str, Any]
    thresholds: dict[str, Any]
    test_cases: list[dict[str, Any]]
    is_active: bool
    change_note: str | None = None
    created_at: datetime


class RuleOut(ORMModel):
    id: uuid.UUID
    code: str
    name: str
    description: str
    exception_type: ExceptionType
    severity: Severity
    applies_to: list[str]
    is_enabled: bool
    is_system: bool
    active_version: int | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    conditions: dict[str, Any] = Field(default_factory=dict)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)
    updated_at: datetime | None = None


class RuleDetail(RuleOut):
    versions: list[RuleVersionOut] = Field(default_factory=list)


class RuleUpdate(ORMModel):
    is_enabled: bool | None = None
    severity: Severity | None = None
    config: dict[str, Any] | None = None
    conditions: dict[str, Any] | None = None
    thresholds: dict[str, Any] | None = None
    test_cases: list[dict[str, Any]] | None = None
    change_note: str | None = Field(default=None, max_length=255)


class ExceptionSummaryRow(ORMModel):
    key: str
    label: str
    count: int


class ExceptionSummary(ORMModel):
    total: int
    open_count: int
    by_severity: list[ExceptionSummaryRow]
    by_type: list[ExceptionSummaryRow]
    by_status: list[ExceptionSummaryRow]
    unassigned_to_case: int
    mean_detections: float


class EntityOption(ORMModel):
    id: uuid.UUID
    label: str


class PriorityOption(ORMModel):
    value: Priority
    label: str
