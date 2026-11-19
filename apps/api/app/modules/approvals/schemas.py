"""Approval schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.domain.enums import ActionType, ApprovalStatus, ResolutionStatus, RiskLevel
from app.schemas.common import ORMModel


class ApproverRef(ORMModel):
    id: uuid.UUID
    full_name: str
    email: str


class ApprovalOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    case_number: str | None = None
    case_title: str | None = None
    resolution_id: uuid.UUID | None = None
    resolution_status: ResolutionStatus | None = None
    action_type: ActionType
    title: str
    description: str = ""
    requester: ApproverRef | None = None
    approver_role: str | None = None
    assigned_approver: ApproverRef | None = None
    risk_level: RiskLevel
    status: ApprovalStatus
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    overdue: bool = False
    decided_at: datetime | None = None
    decided_by: ApproverRef | None = None
    decision_note: str | None = None
    created_at: datetime
    can_decide: bool = False


class ApprovalDecisionRequest(ORMModel):
    comment: str | None = Field(default=None, max_length=4000)
    execute_after_approval: bool = False


class ApprovalDecisionOut(ORMModel):
    approval: ApprovalOut
    resolution_status: ResolutionStatus | None = None
    execution_error: str | None = None


class ApprovalStats(ORMModel):
    pending: int
    overdue: int
    approved_today: int
    rejected_today: int
    average_decision_hours: float
    by_risk: dict[str, int] = Field(default_factory=dict)


class ApprovalDecisionRecord(ORMModel):
    id: uuid.UUID
    decision: str
    decided_by_name: str | None = None
    comment: str | None = None
    created_at: datetime


class ApprovalDetail(ApprovalOut):
    resolution: dict[str, Any] | None = None
    decisions: list[ApprovalDecisionRecord] = Field(default_factory=list)
