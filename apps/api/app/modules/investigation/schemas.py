"""AI investigation schemas: strict model output plus API projections."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.domain.enums import (
    ActionType,
    ExceptionType,
    InvestigationSourceType,
    InvestigationStatus,
    RiskLevel,
    Severity,
)
from app.schemas.common import ORMModel


class EvidenceItem(BaseModel):
    source_type: InvestigationSourceType
    source_id: str | None = Field(default=None, max_length=64)
    document_id: uuid.UUID | None = None
    page_number: int | None = Field(default=None, ge=1, le=5000)
    field_name: str | None = Field(default=None, max_length=60)
    quote: str = Field(min_length=1, max_length=1200)
    relationship: str | None = Field(default=None, max_length=500)


class RootCauseHypothesis(BaseModel):
    hypothesis: str = Field(min_length=1, max_length=1000)
    likelihood: Literal["low", "medium", "high"] = "medium"
    supporting_evidence_count: int = Field(default=0, ge=0, le=100)


class RiskAssessment(BaseModel):
    level: RiskLevel = RiskLevel.MEDIUM
    rationale: str = Field(default="", max_length=1000)


class SuggestedResolutionItem(BaseModel):
    action_type: ActionType
    description: str = Field(min_length=1, max_length=1200)
    rationale: str = Field(default="", max_length=1000)
    risk_level: RiskLevel = RiskLevel.MEDIUM


class InvestigationModelOutput(BaseModel):
    summary: str = Field(min_length=1, max_length=4000)
    exception_types: list[ExceptionType] = Field(default_factory=list, max_length=10)
    root_cause_hypotheses: list[RootCauseHypothesis] = Field(default_factory=list, max_length=6)
    root_cause: str | None = Field(default=None, max_length=2000)
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=30)
    contradicting_evidence: list[EvidenceItem] = Field(default_factory=list, max_length=10)
    missing_information: list[str] = Field(default_factory=list, max_length=20)
    risk_assessment: RiskAssessment = Field(default_factory=RiskAssessment)
    suggested_resolutions: list[SuggestedResolutionItem] = Field(default_factory=list, max_length=6)
    required_actions: list[str] = Field(default_factory=list, max_length=10)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence_basis: str = Field(default="", max_length=600)
    limitations: list[str] = Field(default_factory=list, max_length=10)
    requires_human_review: bool = True


class EvidenceOut(ORMModel):
    id: uuid.UUID
    source_type: InvestigationSourceType
    source_id: str | None = None
    document_id: uuid.UUID | None = None
    page_number: int | None = None
    field_name: str | None = None
    quote: str
    relationship: str | None = None
    is_contradicting: bool
    is_validated: bool
    validation_error: str | None = None


class InvestigationOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    status: InvestigationStatus
    provider: str
    model: str | None = None
    prompt_version: str
    summary: str | None = None
    root_cause: str | None = None
    root_cause_hypotheses: list[dict] = Field(default_factory=list)
    risk_level: RiskLevel | None = None
    confidence: float | None = None
    confidence_basis: str | None = None
    requires_human_review: bool
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    suggested_resolutions: list[dict] = Field(default_factory=list)
    input_tokens: int
    output_tokens: int
    cost_usd: float | None = None
    latency_ms: int | None = None
    error: str | None = None
    error_code: str | None = None
    created_at: datetime
    completed_at: datetime | None = None
    evidence_count: int = 0
    invalid_evidence_count: int = 0
    evidence: list[EvidenceOut] = Field(default_factory=list)


class InvestigationRunRequest(ORMModel):
    include_similar_cases: bool = True
    top_k: int = Field(default=6, ge=1, le=12)
    wait: bool = False


class AcceptSuggestionRequest(ORMModel):
    suggestion_index: int = Field(ge=0, le=10)
    case_id: uuid.UUID | None = None


class CaseInvestigationSummary(ORMModel):
    id: uuid.UUID
    status: InvestigationStatus
    summary: str | None = None
    root_cause: str | None = None
    risk_level: RiskLevel | None = None
    confidence: float | None = None
    created_at: datetime
    completed_at: datetime | None = None


class SeverityOption(ORMModel):
    value: Severity
    label: str
