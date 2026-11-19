"""Resolution schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.domain.enums import ActionType, ResolutionStatus, RiskLevel
from app.schemas.common import ORMModel


class ResolutionCreate(ORMModel):
    action_type: ActionType
    description: str = Field(min_length=3, max_length=4000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    risk_level: RiskLevel | None = None
    request_approval: bool = True
    approver_id: uuid.UUID | None = None
    approver_role: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


class ResolutionOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_number: str | None = None
    investigation_id: uuid.UUID | None = None
    action_type: ActionType
    description: str
    parameters: dict[str, Any]
    supporting_evidence: list[dict[str, Any]] = Field(default_factory=list)
    risk_level: RiskLevel
    expected_outcome: str | None = None
    required_permissions: list[str] = Field(default_factory=list)
    requires_approval: bool
    status: ResolutionStatus
    created_by_id: uuid.UUID | None = None
    created_by_name: str | None = None
    ai_model: str | None = None
    prompt_version: str | None = None
    execution_result: dict[str, Any] | None = None
    error: str | None = None
    executed_at: datetime | None = None
    created_at: datetime
    approval: dict[str, Any] | None = None
    executions: list[dict[str, Any]] = Field(default_factory=list)


class ResolutionCancel(ORMModel):
    reason: str | None = Field(default=None, max_length=1000)


class ActionCatalogItem(ORMModel):
    action_type: str
    label: str
    description: str
    required_permissions: list[str]
    default_risk: str
    external_side_effect: bool
    financial_impact: bool
    policy_notes: str = ""
    parameters_schema: dict[str, Any] = Field(default_factory=dict)


class ApprovalCreateRequest(ORMModel):
    action_type: ActionType = ActionType.CREATE_APPROVAL_REQUEST
    title: str = Field(min_length=3, max_length=250)
    description: str = Field(default="", max_length=4000)
    risk_level: RiskLevel = RiskLevel.MEDIUM
    evidence: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    parameters: dict[str, Any] = Field(default_factory=dict)
    approver_id: uuid.UUID | None = None
    note: str | None = Field(default=None, max_length=1000)
