"""Command centre analytics computed from real database queries."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.domain.enums import (
    ApprovalStatus,
    CaseStatus,
    ExceptionStatus,
    ExceptionType,
    InvoiceStatus,
    JobStatus,
    Priority,
    ResolutionStatus,
    Severity,
    WorkflowStatus,
)
from app.models.ai import AIUsageEvent, ApprovalRequest, Resolution
from app.models.automation import BackgroundJob, WorkflowExecution
from app.models.cases import Case, CaseActivity, ExceptionRecord
from app.models.documents import Document
from app.models.finance import Invoice
from app.models.identity import User
from app.modules.analytics.schemas import (
    ActivityRow,
    CommandCenter,
    DistributionRow,
    Kpi,
    ProcessingMetrics,
    SimplePoint,
    SlaSummary,
    WorkloadRow,
)

ACTIVE_CASE_STATUSES = [
    CaseStatus.OPEN,
    CaseStatus.INVESTIGATING,
    CaseStatus.AWAITING_INFORMATION,
    CaseStatus.AWAITING_APPROVAL,
    CaseStatus.RESOLUTION_IN_PROGRESS,
    CaseStatus.REOPENED,
]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _delta(current: float, previous: float) -> float | None:
    if previous == 0:
        return None if current == 0 else 100.0
    return round((current - previous) / previous * 100, 1)


def _label(value: str) -> str:
    return value.replace("_", " ").title()


def _buckets(start: date, end: date) -> list[date]:
    days = (end - start).days
    return [start + timedelta(days=offset) for offset in range(days + 1)]


def _count(db: Session, model: Any, *conditions: Any) -> int:
    return int(db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)


def _distribution(db: Session, column: Any, model: Any, *conditions: Any) -> list[DistributionRow]:
    rows = db.execute(
        select(column, func.count()).select_from(model).where(*conditions).group_by(column)
    ).all()
    result = []
    for key, count in rows:
        value = key.value if hasattr(key, "value") else str(key)
        result.append(DistributionRow(key=value, label=_label(value), count=int(count)))
    result.sort(key=lambda row: row.count, reverse=True)
    return result


def overview(
    db: Session,
    *,
    org_id: uuid.UUID,
    days: int = 30,
    exception_types: list[ExceptionType] | None = None,
    priorities: list[Priority] | None = None,
) -> CommandCenter:
    now = utcnow()
    start = now - timedelta(days=days)
    previous_start = start - timedelta(days=days)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)

    exception_conditions: list[Any] = [ExceptionRecord.org_id == org_id]
    if exception_types:
        exception_conditions.append(ExceptionRecord.exception_type.in_(exception_types))

    total_exceptions = _count(db, ExceptionRecord, *exception_conditions)
    exceptions_in_range = _count(
        db, ExceptionRecord, *exception_conditions, ExceptionRecord.last_detected_at >= start
    )
    exceptions_previous = _count(
        db,
        ExceptionRecord,
        *exception_conditions,
        ExceptionRecord.last_detected_at >= previous_start,
        ExceptionRecord.last_detected_at < start,
    )

    case_conditions: list[Any] = [Case.org_id == org_id, Case.deleted_at.is_(None)]
    if priorities:
        case_conditions.append(Case.priority.in_(priorities))
    open_cases = _count(db, Case, *case_conditions, Case.status.in_(ACTIVE_CASE_STATUSES))
    critical_cases = _count(
        db, Case, *case_conditions, Case.status.in_(ACTIVE_CASE_STATUSES), Case.severity == Severity.CRITICAL
    )
    high_cases = _count(
        db,
        Case,
        *case_conditions,
        Case.status.in_(ACTIVE_CASE_STATUSES),
        Case.priority.in_([Priority.HIGH, Priority.URGENT]),
    )
    pending_approvals = _count(
        db, ApprovalRequest, ApprovalRequest.org_id == org_id, ApprovalRequest.status == ApprovalStatus.PENDING
    )
    resolved_today = _count(
        db,
        Case,
        Case.org_id == org_id,
        Case.status.in_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
        Case.resolved_at >= start_of_day,
    )
    resolved_previous_day = _count(
        db,
        Case,
        Case.org_id == org_id,
        Case.status.in_([CaseStatus.RESOLVED, CaseStatus.CLOSED]),
        Case.resolved_at >= start_of_day - timedelta(days=1),
        Case.resolved_at < start_of_day,
    )
    ai_resolutions = _count(
        db,
        Resolution,
        Resolution.org_id == org_id,
        Resolution.status == ResolutionStatus.COMPLETED,
        Resolution.investigation_id.is_not(None),
        Resolution.created_at >= start,
    )
    cases_resolved_in_range = list(
        db.scalars(
            select(Case).where(
                Case.org_id == org_id,
                Case.resolved_at.is_not(None),
                Case.resolved_at >= start,
            )
        )
    )
    durations = []
    for case in cases_resolved_in_range:
        created = _aware(case.created_at)
        resolved = _aware(case.resolved_at)
        if created and resolved:
            durations.append((resolved - created).total_seconds() / 3600)
    avg_resolution_hours = round(sum(durations) / len(durations), 1) if durations else 0.0

    invoices_in_range = _count(
        db,
        Invoice,
        Invoice.org_id == org_id,
        Invoice.deleted_at.is_(None),
        Invoice.created_at >= start,
    )
    detection_rate = round(exceptions_in_range / invoices_in_range * 100, 1) if invoices_in_range else 0.0

    workflow_total = _count(
        db, WorkflowExecution, WorkflowExecution.org_id == org_id, WorkflowExecution.created_at >= start
    )
    workflow_success = _count(
        db,
        WorkflowExecution,
        WorkflowExecution.org_id == org_id,
        WorkflowExecution.created_at >= start,
        WorkflowExecution.status == WorkflowStatus.COMPLETED,
    )
    automation_success = round(workflow_success / workflow_total * 100, 1) if workflow_total else 0.0
    failed_jobs = _count(
        db,
        BackgroundJob,
        BackgroundJob.org_id == org_id,
        BackgroundJob.status == JobStatus.FAILED,
        BackgroundJob.created_at >= start,
    )

    buckets = _buckets(start.date(), now.date())
    exception_bucket: dict[date, int] = dict.fromkeys(buckets, 0)
    case_bucket: dict[date, int] = dict.fromkeys(buckets, 0)
    resolution_bucket: dict[date, int] = dict.fromkeys(buckets, 0)
    for record in db.execute(
        select(ExceptionRecord.created_at).where(
            ExceptionRecord.org_id == org_id, ExceptionRecord.created_at >= start
        )
    ).all():
        created = _aware(record[0])
        if created and created.date() in exception_bucket:
            exception_bucket[created.date()] += 1
    for record in db.execute(
        select(Case.created_at).where(Case.org_id == org_id, Case.created_at >= start)
    ).all():
        created = _aware(record[0])
        if created and created.date() in case_bucket:
            case_bucket[created.date()] += 1
    for record in db.execute(
        select(Case.resolved_at).where(
            Case.org_id == org_id, Case.resolved_at.is_not(None), Case.resolved_at >= start
        )
    ).all():
        resolved = _aware(record[0])
        if resolved and resolved.date() in resolution_bucket:
            resolution_bucket[resolved.date()] += 1

    sla_breached = _count(
        db,
        Case,
        Case.org_id == org_id,
        Case.status.in_(ACTIVE_CASE_STATUSES),
        Case.due_at.is_not(None),
        Case.due_at < now,
    )
    due_soon = _count(
        db,
        Case,
        Case.org_id == org_id,
        Case.status.in_(ACTIVE_CASE_STATUSES),
        Case.due_at.is_not(None),
        Case.due_at >= now,
        Case.due_at <= now + timedelta(hours=24),
    )

    workload_rows = db.execute(
        select(Case.assigned_user_id, func.count())
        .where(Case.org_id == org_id, Case.status.in_(ACTIVE_CASE_STATUSES))
        .group_by(Case.assigned_user_id)
    ).all()
    user_ids = [row[0] for row in workload_rows if row[0] is not None]
    users = {
        user.id: user for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}
    workload = [
        WorkloadRow(
            user_id=str(user_id) if user_id else None,
            name=users[user_id].full_name if user_id in users else "Unassigned",
            open_cases=int(count),
            overdue_cases=0,
        )
        for user_id, count in workload_rows
    ]
    workload.sort(key=lambda row: row.open_cases, reverse=True)

    activities = db.scalars(
        select(CaseActivity).where(
            CaseActivity.case_id.in_(select(Case.id).where(Case.org_id == org_id))
        ).order_by(CaseActivity.created_at.desc()).limit(15)
    ).all()
    activity_case_ids = {activity.case_id for activity in activities}
    activity_cases = {
        case.id: case
        for case in db.scalars(select(Case).where(Case.id.in_(activity_case_ids))).all()
    } if activity_case_ids else {}
    actor_ids = {activity.actor_id for activity in activities if activity.actor_id}
    actors = {
        actor.id: actor for actor in db.scalars(select(User).where(User.id.in_(actor_ids))).all()
    } if actor_ids else {}

    usage = db.execute(
        select(
            func.count(),
            func.coalesce(func.sum(AIUsageEvent.input_tokens + AIUsageEvent.output_tokens), 0),
            func.coalesce(func.sum(AIUsageEvent.cost_usd), 0),
            func.coalesce(func.avg(AIUsageEvent.latency_ms), 0),
        ).where(AIUsageEvent.org_id == org_id, AIUsageEvent.created_at >= start)
    ).one()

    processing = ProcessingMetrics(
        documents_by_status=_distribution(
            db, Document.status, Document, Document.org_id == org_id, Document.deleted_at.is_(None)
        ),
        jobs_by_status=_distribution(db, BackgroundJob.status, BackgroundJob, BackgroundJob.org_id == org_id),
        failed_jobs=failed_jobs,
        ai_runs=int(usage[0] or 0),
        ai_tokens=int(usage[1] or 0),
        ai_cost_usd=round(float(usage[2] or 0), 4),
        ai_average_latency_ms=round(float(usage[3] or 0), 1),
    )

    kpis = [
        Kpi(key="total_exceptions", label="Total exceptions", value=total_exceptions, unit="count"),
        Kpi(
            key="open_cases",
            label="Open cases",
            value=open_cases,
            unit="count",
        ),
        Kpi(key="critical_cases", label="Critical cases", value=critical_cases, unit="count"),
        Kpi(key="high_priority_cases", label="High priority cases", value=high_cases, unit="count"),
        Kpi(key="pending_approvals", label="Pending approvals", value=pending_approvals, unit="count"),
        Kpi(
            key="resolved_today",
            label="Resolved today",
            value=resolved_today,
            previous=resolved_previous_day,
            delta_percent=_delta(resolved_today, resolved_previous_day),
            unit="count",
        ),
        Kpi(key="ai_assisted_resolutions", label="AI-assisted resolutions", value=ai_resolutions, unit="count"),
        Kpi(
            key="average_resolution_hours",
            label="Average resolution time",
            value=avg_resolution_hours,
            unit="hours",
        ),
        Kpi(
            key="detection_rate",
            label="Exception detection rate",
            value=detection_rate,
            unit="percent",
            detail="Exceptions detected per 100 invoices created in the selected range",
        ),
        Kpi(
            key="automation_success_rate",
            label="Automation success rate",
            value=automation_success,
            unit="percent",
            detail="Completed workflow executions divided by all executions",
        ),
        Kpi(key="failed_jobs", label="Failed background jobs", value=failed_jobs, unit="count"),
    ]

    return CommandCenter(
        range_days=days,
        generated_at=now,
        kpis=kpis,
        exception_trend=[
            SimplePoint(bucket=bucket.isoformat(), value=exception_bucket[bucket]) for bucket in buckets
        ],
        case_trend=[SimplePoint(bucket=bucket.isoformat(), value=case_bucket[bucket]) for bucket in buckets],
        resolution_trend=[
            SimplePoint(bucket=bucket.isoformat(), value=resolution_bucket[bucket]) for bucket in buckets
        ],
        exception_distribution=_distribution(db, ExceptionRecord.exception_type, ExceptionRecord, *exception_conditions),
        priority_distribution=_distribution(db, Case.priority, Case, *case_conditions),
        resolution_distribution=_distribution(db, Resolution.action_type, Resolution, Resolution.org_id == org_id),
        sla=SlaSummary(
            breached=sla_breached,
            due_within_24h=due_soon,
            average_resolution_hours=avg_resolution_hours,
        ),
        workload=workload,
        recent_activity=[
            ActivityRow(
                id=str(activity.id),
                case_id=str(activity.case_id),
                case_number=activity_cases[activity.case_id].case_number
                if activity.case_id in activity_cases
                else "",
                case_title=activity_cases[activity.case_id].title
                if activity.case_id in activity_cases
                else "",
                activity_type=activity.activity_type,
                summary=activity.summary,
                actor_name=actors[activity.actor_id].full_name if activity.actor_id in actors else None,
                created_at=activity.created_at,
            )
            for activity in activities
        ],
        processing=processing,
        counts={
            "exceptions_in_range": exceptions_in_range,
            "exceptions_previous_range": exceptions_previous,
            "cases_resolved_in_range": len(cases_resolved_in_range),
            "invoices_in_range": invoices_in_range,
            "workflow_executions": workflow_total,
            "open_invoices": _count(
                db,
                Invoice,
                Invoice.org_id == org_id,
                Invoice.deleted_at.is_(None),
                Invoice.status.notin_([InvoiceStatus.CANCELLED, InvoiceStatus.REJECTED]),
            ),
            "open_exceptions": _count(
                db,
                ExceptionRecord,
                ExceptionRecord.org_id == org_id,
                ExceptionRecord.status.in_(
                    [ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.LINKED]
                ),
            ),
        },
    )


def resolution_time_series(db: Session, *, org_id: uuid.UUID, days: int = 30) -> list[dict[str, Any]]:
    start = utcnow() - timedelta(days=days)
    cases = db.scalars(
        select(Case).where(
            Case.org_id == org_id, Case.resolved_at.is_not(None), Case.resolved_at >= start
        )
    ).all()
    buckets: dict[str, list[float]] = {}
    for case in cases:
        resolved = _aware(case.resolved_at)
        created = _aware(case.created_at)
        if resolved is None or created is None:
            continue
        key = resolved.date().isoformat()
        buckets.setdefault(key, []).append((resolved - created).total_seconds() / 3600)
    return [
        {
            "bucket": key,
            "average_hours": round(sum(values) / len(values), 2),
            "resolved": len(values),
        }
        for key, values in sorted(buckets.items())
    ]


def ai_usage(db: Session, *, org_id: uuid.UUID, days: int = 30) -> dict[str, Any]:
    start = utcnow() - timedelta(days=days)
    rows = db.execute(
        select(
            AIUsageEvent.purpose,
            func.count(),
            func.coalesce(func.sum(AIUsageEvent.input_tokens), 0),
            func.coalesce(func.sum(AIUsageEvent.output_tokens), 0),
            func.coalesce(func.sum(AIUsageEvent.cost_usd), 0),
            func.coalesce(func.avg(AIUsageEvent.latency_ms), 0),
        )
        .where(AIUsageEvent.org_id == org_id, AIUsageEvent.created_at >= start)
        .group_by(AIUsageEvent.purpose)
    ).all()
    by_model = db.execute(
        select(AIUsageEvent.provider, AIUsageEvent.model, func.count(), func.coalesce(func.sum(AIUsageEvent.cost_usd), 0))
        .where(AIUsageEvent.org_id == org_id, AIUsageEvent.created_at >= start)
        .group_by(AIUsageEvent.provider, AIUsageEvent.model)
    ).all()
    return {
        "range_days": days,
        "by_purpose": [
            {
                "purpose": purpose,
                "runs": int(count),
                "input_tokens": int(input_tokens),
                "output_tokens": int(output_tokens),
                "cost_usd": round(float(cost), 4),
                "average_latency_ms": round(float(latency), 1),
            }
            for purpose, count, input_tokens, output_tokens, cost, latency in rows
        ],
        "by_model": [
            {
                "provider": provider,
                "model": model,
                "runs": int(count),
                "cost_usd": round(float(cost), 4),
            }
            for provider, model, count, cost in by_model
        ],
    }
