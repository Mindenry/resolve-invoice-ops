"""Analytics schemas for the operations command centre."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from app.schemas.common import ORMModel


class Kpi(ORMModel):
    key: str
    label: str
    value: float
    previous: float | None = None
    delta_percent: float | None = None
    unit: str = "count"
    detail: str | None = None


class SimplePoint(ORMModel):
    bucket: str
    value: float
    secondary: float | None = None


class DistributionRow(ORMModel):
    key: str
    label: str
    count: int


class SlaSummary(ORMModel):
    breached: int
    due_within_24h: int
    average_resolution_hours: float


class WorkloadRow(ORMModel):
    user_id: str | None = None
    name: str
    open_cases: int
    overdue_cases: int


class ActivityRow(ORMModel):
    id: str
    case_id: str
    case_number: str
    case_title: str
    activity_type: str
    summary: str
    actor_name: str | None = None
    created_at: datetime


class ProcessingMetrics(ORMModel):
    documents_by_status: list[DistributionRow] = Field(default_factory=list)
    jobs_by_status: list[DistributionRow] = Field(default_factory=list)
    failed_jobs: int = 0
    ai_runs: int = 0
    ai_tokens: int = 0
    ai_cost_usd: float = 0.0
    ai_average_latency_ms: float = 0.0


class CommandCenter(ORMModel):
    range_days: int
    generated_at: datetime
    kpis: list[Kpi]
    exception_trend: list[SimplePoint]
    case_trend: list[SimplePoint]
    resolution_trend: list[SimplePoint]
    exception_distribution: list[DistributionRow]
    priority_distribution: list[DistributionRow]
    resolution_distribution: list[DistributionRow]
    sla: SlaSummary
    workload: list[WorkloadRow]
    recent_activity: list[ActivityRow]
    processing: ProcessingMetrics
    counts: dict[str, Any] = Field(default_factory=dict)


class AnalyticsOverviewResponse(ORMModel):
    data: CommandCenter
