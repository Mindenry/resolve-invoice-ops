"""Case lifecycle, assignment, comments, SLA and merge logic."""

from __future__ import annotations

import uuid
from datetime import UTC, timedelta
from typing import Any

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.jsonfilters import json_array_contains
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.domain.enums import (
    CaseStatus,
    CommentVisibility,
    EventType,
    ExceptionStatus,
    NotificationType,
    Priority,
    Severity,
)
from app.models.cases import Case, CaseActivity, CaseAssignment, CaseComment, CaseLink, ExceptionRecord
from app.models.identity import Membership, User
from app.modules.cases.schemas import (
    CaseActivityOut,
    CaseCommentOut,
    CaseDetail,
    CaseExceptionOut,
    CaseLinkOut,
    CaseSummary,
    TimelineItem,
    UserRef,
)
from app.services.audit import record_audit
from app.services.events import emit_event
from app.services.notifications import notify, user_ids_with_permission

logger = get_logger(__name__)

PRIORITY_FROM_SEVERITY: dict[Severity, Priority] = {
    Severity.CRITICAL: Priority.URGENT,
    Severity.HIGH: Priority.HIGH,
    Severity.MEDIUM: Priority.MEDIUM,
    Severity.LOW: Priority.LOW,
}

SLA_HOURS: dict[Priority, int] = {
    Priority.URGENT: 8,
    Priority.HIGH: 24,
    Priority.MEDIUM: 48,
    Priority.LOW: 72,
}

ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.OPEN: {
        CaseStatus.INVESTIGATING,
        CaseStatus.AWAITING_INFORMATION,
        CaseStatus.RESOLUTION_IN_PROGRESS,
        CaseStatus.AWAITING_APPROVAL,
        CaseStatus.RESOLVED,
        CaseStatus.CLOSED,
        CaseStatus.CANCELLED,
    },
    CaseStatus.INVESTIGATING: {
        CaseStatus.AWAITING_INFORMATION,
        CaseStatus.AWAITING_APPROVAL,
        CaseStatus.RESOLUTION_IN_PROGRESS,
        CaseStatus.RESOLVED,
        CaseStatus.CLOSED,
        CaseStatus.CANCELLED,
    },
    CaseStatus.AWAITING_INFORMATION: {
        CaseStatus.INVESTIGATING,
        CaseStatus.RESOLUTION_IN_PROGRESS,
        CaseStatus.RESOLVED,
        CaseStatus.CANCELLED,
    },
    CaseStatus.AWAITING_APPROVAL: {
        CaseStatus.INVESTIGATING,
        CaseStatus.RESOLUTION_IN_PROGRESS,
        CaseStatus.RESOLVED,
        CaseStatus.CANCELLED,
    },
    CaseStatus.RESOLUTION_IN_PROGRESS: {
        CaseStatus.AWAITING_INFORMATION,
        CaseStatus.AWAITING_APPROVAL,
        CaseStatus.RESOLVED,
        CaseStatus.CANCELLED,
    },
    CaseStatus.REOPENED: {
        CaseStatus.INVESTIGATING,
        CaseStatus.RESOLUTION_IN_PROGRESS,
        CaseStatus.RESOLVED,
        CaseStatus.CANCELLED,
    },
    CaseStatus.RESOLVED: {CaseStatus.REOPENED, CaseStatus.CLOSED},
    CaseStatus.CLOSED: {CaseStatus.REOPENED},
    CaseStatus.CANCELLED: set(),
}


# ---------------------------------------------------------------------------- helpers


def get_case(db: Session, *, org_id: uuid.UUID, case_id: uuid.UUID) -> Case:
    case = db.scalar(
        select(Case).where(Case.id == case_id, Case.org_id == org_id, Case.deleted_at.is_(None))
    )
    if case is None:
        raise NotFoundError("Case not found.", code="case_not_found")
    return case


def log_activity(
    db: Session,
    *,
    case: Case,
    actor_id: uuid.UUID | None,
    activity_type: str,
    summary: str,
    payload: dict[str, Any] | None = None,
) -> CaseActivity:
    activity = CaseActivity(
        case_id=case.id,
        actor_id=actor_id,
        activity_type=activity_type,
        summary=summary[:400],
        payload=payload or {},
    )
    db.add(activity)
    case.last_activity_at = utcnow()
    return activity


def link_entity(
    db: Session, *, case: Case, entity_type: str, entity_id: uuid.UUID, label: str | None = None
) -> CaseLink:
    existing = db.scalar(
        select(CaseLink).where(
            CaseLink.case_id == case.id,
            CaseLink.entity_type == entity_type,
            CaseLink.entity_id == entity_id,
        )
    )
    if existing is not None:
        return existing
    link = CaseLink(
        org_id=case.org_id,
        case_id=case.id,
        entity_type=entity_type,
        entity_id=entity_id,
        label=label,
    )
    db.add(link)
    db.flush()
    return link


def _ensure_assignee(db: Session, org_id: uuid.UUID, user_id: uuid.UUID | None) -> User | None:
    if user_id is None:
        return None
    user = db.get(User, user_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.org_id == org_id,
            Membership.is_active.is_(True),
        )
    )
    if user is None or not user.is_active or membership is None:
        raise BadRequestError("Assignee must be an active member of the organization.", code="invalid_assignee")
    return user


def next_case_number(db: Session, org_id: uuid.UUID, *, attempt: int = 0) -> str:
    year = utcnow().year
    prefix = f"CASE-{year}-"
    last = db.scalar(
        select(func.max(Case.case_number)).where(
            Case.org_id == org_id, Case.case_number.like(f"{prefix}%")
        )
    )
    sequence = 1
    if last:
        try:
            sequence = int(last.rsplit("-", 1)[1]) + 1
        except (IndexError, ValueError):
            sequence = db.scalar(select(func.count()).select_from(Case).where(Case.org_id == org_id)) + 1
    return f"{prefix}{sequence + attempt:04d}"


# ------------------------------------------------------------------------- create/update


def _lock_case_number_allocation(db: Session, org_id: uuid.UUID) -> None:
    """Serialize case-number allocation per organization on PostgreSQL.

    ``next_case_number`` reads MAX(...) and therefore two concurrent
    transactions can compute the same number. A transaction-scoped advisory
    lock removes the race without a schema change; SQLite serializes writers.
    """
    bind = db.get_bind()
    if bind is not None and bind.dialect.name == "postgresql":
        key = int.from_bytes(org_id.bytes[:8], "big", signed=True)
        db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


def create_case(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    title: str,
    description: str = "",
    priority: Priority = Priority.MEDIUM,
    severity: Severity | None = None,
    assigned_user_id: uuid.UUID | None = None,
    tags: list[str] | None = None,
    sla_hours: int | None = None,
    links: list[tuple[str, uuid.UUID, str | None]] | None = None,
    exception_ids: list[uuid.UUID] | None = None,
    notify_team: bool = True,
) -> Case:
    _ensure_assignee(db, org_id, assigned_user_id)
    _lock_case_number_allocation(db, org_id)
    priority = Priority(priority) if isinstance(priority, str) else priority
    severity = Severity(severity) if isinstance(severity, str) else (severity or Severity.MEDIUM)
    case: Case | None = None
    for attempt in range(5):
        case = Case(
            org_id=org_id,
            case_number=next_case_number(db, org_id, attempt=attempt),
            title=title[:250],
            description=description,
            status=CaseStatus.OPEN,
            priority=priority,
            severity=severity,
            assigned_user_id=assigned_user_id,
            created_by_id=actor_id,
            sla_hours=sla_hours or SLA_HOURS[priority],
            tags=[tag.strip()[:40] for tag in (tags or []) if tag.strip()][:20],
            last_activity_at=utcnow(),
        )
        case.due_at = utcnow() + timedelta(hours=case.sla_hours)
        try:
            with db.begin_nested():
                db.add(case)
                db.flush()
            break
        except IntegrityError:
            db.expunge(case)
            case = None
            continue
    if case is None:
        raise ConflictError("Could not allocate a case number; please retry.", code="case_number_conflict")

    for entity_type, entity_id, label in links or []:
        link_entity(db, case=case, entity_type=entity_type, entity_id=entity_id, label=label)

    if exception_ids:
        attach_exceptions(db, case=case, exception_ids=exception_ids)

    if assigned_user_id:
        db.add(
            CaseAssignment(
                case_id=case.id, assigned_to_id=assigned_user_id, assigned_by_id=actor_id, reason="Initial assignment"
            )
        )

    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="CASE_CREATED",
        summary=f"Case {case.case_number} created: {case.title}",
        payload={"priority": priority.value, "severity": severity.value},
    )
    record_audit(
        db,
        org_id=org_id,
        action="case.created",
        entity_type="case",
        entity_id=case.id,
        summary=f"Case {case.case_number} created",
        actor_id=actor_id,
        after={"title": case.title, "priority": priority.value, "status": case.status.value},
    )
    emit_event(
        db,
        org_id=org_id,
        event_type=EventType.CASE_CREATED,
        entity_type="CASE",
        entity_id=case.id,
        payload={"case_number": case.case_number, "title": case.title, "priority": case.priority.value},
    )
    if notify_team:
        recipients = user_ids_with_permission(db, org_id=org_id, permission="case:read")
        notify(
            db,
            org_id=org_id,
            user_id=assigned_user_id,
            type=NotificationType.CASE_CREATED if priority in {Priority.LOW, Priority.MEDIUM} else NotificationType.HIGH_PRIORITY_CASE,
            title=f"{case.case_number}: {case.title}",
            body=f"A new {priority.value.lower()} priority case was opened.",
            entity_type="CASE",
            entity_id=case.id,
            payload={"case_number": case.case_number},
            send_mail=priority in {Priority.HIGH, Priority.URGENT},
        )
        for user_id in recipients:
            if user_id == assigned_user_id:
                continue
            notify(
                db,
                org_id=org_id,
                user_id=user_id,
                type=NotificationType.CASE_CREATED,
                title=f"New case {case.case_number}",
                body=case.title,
                entity_type="CASE",
                entity_id=case.id,
            )
    return case


def attach_exceptions(db: Session, *, case: Case, exception_ids: list[uuid.UUID]) -> int:
    attached = 0
    for exception_id in exception_ids:
        record = db.scalar(
            select(ExceptionRecord).where(
                ExceptionRecord.id == exception_id, ExceptionRecord.org_id == case.org_id
            )
        )
        if record is None:
            continue
        record.case_id = case.id
        if record.status == ExceptionStatus.OPEN:
            record.status = ExceptionStatus.ACKNOWLEDGED
        link_entity(db, case=case, entity_type="EXCEPTION", entity_id=record.id, label=record.title)
        attached += 1
    return attached


def update_case(
    db: Session,
    *,
    case: Case,
    actor_id: uuid.UUID | None,
    changes: dict[str, Any],
    summary: str = "Case updated",
) -> Case:
    before: dict[str, Any] = {}
    after: dict[str, Any] = {}
    for field, value in changes.items():
        if value is None:
            continue
        current = getattr(case, field)
        if current != value:
            before[field] = current.value if hasattr(current, "value") else str(current)
            after[field] = value.value if hasattr(value, "value") else str(value)
            setattr(case, field, value)
    if changes.get("priority") is not None and changes["priority"] != Priority.MEDIUM:
        case.due_at = (case.created_at + timedelta(hours=SLA_HOURS[changes["priority"]])) if case.created_at else case.due_at
    if changes.get("sla_hours") is not None:
        base = case.created_at or utcnow()
        case.due_at = base + timedelta(hours=changes["sla_hours"])
    if before:
        log_activity(
            db, case=case, actor_id=actor_id, activity_type="CASE_UPDATED", summary=summary, payload=after
        )
        record_audit(
            db,
            org_id=case.org_id,
            action="case.updated",
            entity_type="case",
            entity_id=case.id,
            summary=summary,
            actor_id=actor_id,
            before=before,
            after=after,
        )
        if "priority" in after:
            emit_event(
                db,
                org_id=case.org_id,
                event_type=EventType.CASE_PRIORITY_CHANGED,
                entity_type="CASE",
                entity_id=case.id,
                payload={"previous": before.get("priority"), "current": after.get("priority")},
            )
    return case


def transition(
    db: Session,
    *,
    case: Case,
    new_status: CaseStatus,
    actor_id: uuid.UUID | None,
    note: str | None = None,
    resolution_summary: str | None = None,
) -> Case:
    if new_status == case.status:
        return case
    allowed = ALLOWED_TRANSITIONS.get(case.status, set())
    if new_status not in allowed:
        raise BadRequestError(
            f"Cannot transition a case from {case.status.value} to {new_status.value}.",
            code="invalid_case_transition",
            details={"allowed": sorted(s.value for s in allowed)},
        )

    previous = case.status
    case.status = new_status
    now = utcnow()
    if new_status in {CaseStatus.RESOLVED, CaseStatus.CLOSED}:
        if new_status == CaseStatus.RESOLVED:
            if not (resolution_summary or case.resolution_summary):
                raise BadRequestError(
                    "A resolution summary is required before resolving a case.",
                    code="resolution_summary_required",
                )
            case.resolution_summary = resolution_summary or case.resolution_summary
            case.resolved_at = now
        else:
            case.closed_at = now
            case.resolved_at = case.resolved_at or now
    elif new_status == CaseStatus.REOPENED:
        case.resolved_at = None
        case.closed_at = None
    elif new_status == CaseStatus.CANCELLED:
        case.closed_at = now

    if new_status in {CaseStatus.RESOLVED, CaseStatus.CLOSED}:
        for record in db.scalars(select(ExceptionRecord).where(ExceptionRecord.case_id == case.id)).all():
            if record.status in {ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.LINKED}:
                record.status = ExceptionStatus.RESOLVED
                record.resolved_at = now
                record.resolution_note = resolution_summary or "Resolved with case."

    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="STATUS_CHANGED",
        summary=f"Status changed from {previous.value} to {new_status.value}",
        payload={"previous": previous.value, "current": new_status.value, "note": note},
    )
    record_audit(
        db,
        org_id=case.org_id,
        action="case.status_changed",
        entity_type="case",
        entity_id=case.id,
        summary=f"Case {case.case_number}: {previous.value} -> {new_status.value}",
        actor_id=actor_id,
        before={"status": previous.value},
        after={"status": new_status.value},
    )
    if new_status == CaseStatus.RESOLVED:
        emit_event(
            db,
            org_id=case.org_id,
            event_type=EventType.CASE_RESOLVED,
            entity_type="CASE",
            entity_id=case.id,
            payload={"case_number": case.case_number, "summary": resolution_summary},
        )
        if case.assigned_user_id:
            notify(
                db,
                org_id=case.org_id,
                user_id=case.assigned_user_id,
                type=NotificationType.CASE_RESOLVED,
                title=f"Case {case.case_number} resolved",
                body=(resolution_summary or "")[:500],
                entity_type="CASE",
                entity_id=case.id,
                send_mail=False,
            )
    return case


def assign_case(
    db: Session, *, case: Case, user_id: uuid.UUID | None, actor_id: uuid.UUID | None, reason: str | None = None
) -> Case:
    _ensure_assignee(db, case.org_id, user_id)
    if case.assigned_user_id == user_id:
        return case
    now = utcnow()
    for assignment in db.scalars(
        select(CaseAssignment).where(
            CaseAssignment.case_id == case.id, CaseAssignment.unassigned_at.is_(None)
        )
    ):
        assignment.unassigned_at = now
    db.add(
        CaseAssignment(
            case_id=case.id, assigned_to_id=user_id, assigned_by_id=actor_id, reason=reason, assigned_at=now
        )
    )
    previous = case.assigned_user_id
    case.assigned_user_id = user_id
    case.last_activity_at = now
    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="ASSIGNED",
        summary="Case assignment changed",
        payload={"from": str(previous) if previous else None, "to": str(user_id) if user_id else None},
    )
    record_audit(
        db,
        org_id=case.org_id,
        action="case.assigned",
        entity_type="case",
        entity_id=case.id,
        summary=f"Case {case.case_number} reassigned",
        actor_id=actor_id,
        before={"assigned_user_id": str(previous) if previous else None},
        after={"assigned_user_id": str(user_id) if user_id else None},
    )
    emit_event(
        db,
        org_id=case.org_id,
        event_type=EventType.CASE_ASSIGNED,
        entity_type="CASE",
        entity_id=case.id,
        payload={"assigned_user_id": str(user_id) if user_id else None},
    )
    if user_id:
        notify(
            db,
            org_id=case.org_id,
            user_id=user_id,
            type=NotificationType.CASE_ASSIGNED,
            title=f"Case {case.case_number} assigned to you",
            body=case.title,
            entity_type="CASE",
            entity_id=case.id,
            send_mail=True,
        )
    return case


def add_comment(
    db: Session,
    *,
    case: Case,
    author: User,
    body: str,
    visibility: CommentVisibility = CommentVisibility.INTERNAL,
) -> CaseComment:
    comment = CaseComment(case_id=case.id, author_id=author.id, body=body, visibility=visibility)
    db.add(comment)
    db.flush()
    if case.first_response_at is None:
        case.first_response_at = utcnow()
    log_activity(
        db,
        case=case,
        actor_id=author.id,
        activity_type="COMMENT_ADDED",
        summary=f"{visibility.value.title()} comment added",
        payload={"comment_id": str(comment.id)},
    )
    record_audit(
        db,
        org_id=case.org_id,
        action="case.comment_added",
        entity_type="case",
        entity_id=case.id,
        summary="Comment added",
        actor=author,
    )
    emit_event(
        db,
        org_id=case.org_id,
        event_type=EventType.CASE_COMMENTED,
        entity_type="CASE",
        entity_id=case.id,
        payload={"visibility": visibility.value, "excerpt": body[:200]},
    )
    return comment


def escalate_case(db: Session, *, case: Case, actor_id: uuid.UUID | None, reason: str, priority: Priority) -> Case:
    previous = case.priority
    case.priority = priority
    case.due_at = utcnow() + timedelta(hours=SLA_HOURS[priority])
    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="ESCALATED",
        summary=f"Case escalated to {priority.value}: {reason}",
        payload={"previous": previous.value, "reason": reason},
    )
    record_audit(
        db,
        org_id=case.org_id,
        action="case.escalated",
        entity_type="case",
        entity_id=case.id,
        summary=f"Case {case.case_number} escalated to {priority.value}",
        actor_id=actor_id,
        before={"priority": previous.value},
        after={"priority": priority.value},
    )
    emit_event(
        db,
        org_id=case.org_id,
        event_type=EventType.CASE_ESCALATED,
        entity_type="CASE",
        entity_id=case.id,
        payload={"priority": priority.value, "reason": reason},
    )
    recipients = user_ids_with_permission(db, org_id=case.org_id, permission="case:assign")
    for user_id in recipients:
        notify(
            db,
            org_id=case.org_id,
            user_id=user_id,
            type=NotificationType.CASE_ESCALATED,
            title=f"Case {case.case_number} escalated",
            body=reason[:500],
            entity_type="CASE",
            entity_id=case.id,
            send_mail=True,
        )
    return case


def merge_cases(
    db: Session, *, target: Case, source: Case, actor_id: uuid.UUID | None, note: str | None = None
) -> Case:
    if target.id == source.id:
        raise BadRequestError("A case cannot be merged into itself.", code="invalid_merge")
    if target.org_id != source.org_id:
        raise NotFoundError("Case not found.", code="case_not_found")
    if source.status in {CaseStatus.CLOSED, CaseStatus.CANCELLED}:
        raise BadRequestError("The source case is already closed or cancelled.", code="invalid_merge")
    now = utcnow()
    for record in db.scalars(select(ExceptionRecord).where(ExceptionRecord.case_id == source.id)).all():
        record.case_id = target.id
    for link in db.scalars(select(CaseLink).where(CaseLink.case_id == source.id)).all():
        entity_type, entity_id, label = link.entity_type, link.entity_id, link.label
        db.delete(link)
        link_entity(db, case=target, entity_type=entity_type, entity_id=entity_id, label=label)
    for comment in db.scalars(select(CaseComment).where(CaseComment.case_id == source.id)).all():
        comment.case_id = target.id
    source.merged_into_case_id = target.id
    source.status = CaseStatus.CLOSED
    source.closed_at = now
    source.resolution_summary = (source.resolution_summary or "") + f"\nMerged into {target.case_number}."
    log_activity(
        db,
        case=target,
        actor_id=actor_id,
        activity_type="CASE_MERGED",
        summary=f"Case {source.case_number} merged into this case",
        payload={"source_case_id": str(source.id), "note": note},
    )
    log_activity(
        db,
        case=source,
        actor_id=actor_id,
        activity_type="CASE_MERGED",
        summary=f"Case merged into {target.case_number}",
        payload={"target_case_id": str(target.id)},
    )
    record_audit(
        db,
        org_id=target.org_id,
        action="case.merged",
        entity_type="case",
        entity_id=target.id,
        summary=f"{source.case_number} merged into {target.case_number}",
        actor_id=actor_id,
    )
    return target


# ------------------------------------------------------------------------- serialization


def _user_ref(user: User | None) -> UserRef | None:
    if user is None:
        return None
    return UserRef(id=user.id, full_name=user.full_name, email=user.email, avatar_color=user.avatar_color)


def _summary_from(case: Case, assignee: User | None, exception_count: int) -> CaseSummary:
    due_at = case.due_at
    if due_at is not None and due_at.tzinfo is None:
        due_at = due_at.replace(tzinfo=UTC)
    breached = bool(
        due_at
        and case.status not in {CaseStatus.RESOLVED, CaseStatus.CLOSED, CaseStatus.CANCELLED}
        and due_at < utcnow()
    )
    return CaseSummary(
        id=case.id,
        case_number=case.case_number,
        title=case.title,
        status=case.status,
        priority=case.priority,
        severity=case.severity,
        assigned_user=_user_ref(assignee),
        due_at=case.due_at,
        sla_hours=case.sla_hours,
        sla_breached=breached,
        tags=list(case.tags or []),
        exception_count=exception_count,
        is_demo=case.is_demo,
        created_at=case.created_at,
        last_activity_at=case.last_activity_at,
    )


def _summary(db: Session, case: Case) -> CaseSummary:
    assignee = db.get(User, case.assigned_user_id) if case.assigned_user_id else None
    exception_count = db.scalar(
        select(func.count()).select_from(ExceptionRecord).where(ExceptionRecord.case_id == case.id)
    ) or 0
    return _summary_from(case, assignee, exception_count)


def _summaries(db: Session, cases: list[Case]) -> list[CaseSummary]:
    """Build list projections with two batched queries instead of per-row lookups."""
    if not cases:
        return []
    user_ids = {case.assigned_user_id for case in cases if case.assigned_user_id}
    assignees: dict[uuid.UUID, User] = {}
    if user_ids:
        assignees = {
            user.id: user
            for user in db.scalars(select(User).where(User.id.in_(user_ids)))
        }
    counts = dict(
        db.execute(
            select(ExceptionRecord.case_id, func.count())
            .where(ExceptionRecord.case_id.in_([case.id for case in cases]))
            .group_by(ExceptionRecord.case_id)
        ).all()
    )
    return [
        _summary_from(case, assignees.get(case.assigned_user_id), counts.get(case.id, 0))
        for case in cases
    ]


def detail(db: Session, case: Case, *, comment_limit: int = 100) -> CaseDetail:
    summary = _summary(db, case)
    user_ids: set[uuid.UUID] = set()
    comments = list(
        db.scalars(
            select(CaseComment)
            .where(CaseComment.case_id == case.id, CaseComment.deleted_at.is_(None))
            .order_by(CaseComment.created_at.desc())
            .limit(comment_limit)
        )
    )
    activities = list(
        db.scalars(
            select(CaseActivity)
            .where(CaseActivity.case_id == case.id)
            .order_by(CaseActivity.created_at.desc())
            .limit(100)
        )
    )
    for comment in comments:
        if comment.author_id:
            user_ids.add(comment.author_id)
    for activity in activities:
        if activity.actor_id:
            user_ids.add(activity.actor_id)
    if case.created_by_id:
        user_ids.add(case.created_by_id)
    users = {
        user.id: user for user in db.scalars(select(User).where(User.id.in_(user_ids))).all()
    } if user_ids else {}

    exceptions = list(
        db.scalars(
            select(ExceptionRecord)
            .where(ExceptionRecord.case_id == case.id)
            .order_by(ExceptionRecord.last_detected_at.desc())
        )
    )
    links = list(db.scalars(select(CaseLink).where(CaseLink.case_id == case.id).order_by(CaseLink.created_at)))

    return CaseDetail(
        **summary.model_dump(),
        description=case.description,
        resolution_summary=case.resolution_summary,
        resolved_at=case.resolved_at,
        closed_at=case.closed_at,
        first_response_at=case.first_response_at,
        created_by=_user_ref(users.get(case.created_by_id)) if case.created_by_id else None,
        merged_into_case_id=case.merged_into_case_id,
        links=[CaseLinkOut.model_validate(link) for link in links],
        exceptions=[CaseExceptionOut.model_validate(record) for record in exceptions],
        comments=[
            CaseCommentOut(
                id=comment.id,
                author_id=comment.author_id,
                author_name=users.get(comment.author_id).full_name if comment.author_id in users else None,
                body=comment.body,
                visibility=comment.visibility,
                created_at=comment.created_at,
                edited_at=comment.edited_at,
            )
            for comment in reversed(comments)
        ],
        activities=[
            CaseActivityOut(
                id=activity.id,
                actor_id=activity.actor_id,
                actor_name=users.get(activity.actor_id).full_name if activity.actor_id in users else None,
                activity_type=activity.activity_type,
                summary=activity.summary,
                payload=activity.payload,
                created_at=activity.created_at,
            )
            for activity in activities
        ],
    )


def timeline(db: Session, case: Case) -> list[TimelineItem]:
    comments = list(
        db.scalars(
            select(CaseComment)
            .where(CaseComment.case_id == case.id, CaseComment.deleted_at.is_(None))
            .order_by(CaseComment.created_at.desc())
            .limit(200)
        )
    )
    activities = list(
        db.scalars(
            select(CaseActivity)
            .where(CaseActivity.case_id == case.id)
            .order_by(CaseActivity.created_at.desc())
            .limit(200)
        )
    )
    user_ids = {c.author_id for c in comments if c.author_id} | {a.actor_id for a in activities if a.actor_id}
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids))).all()} if user_ids else {}
    items = [
        TimelineItem(
            kind="COMMENT",
            id=comment.id,
            actor_name=users.get(comment.author_id).full_name if comment.author_id in users else None,
            summary=comment.body[:160],
            detail=comment.body,
            visibility=comment.visibility,
            created_at=comment.created_at,
        )
        for comment in comments
    ] + [
        TimelineItem(
            kind="ACTIVITY",
            id=activity.id,
            actor_name=users.get(activity.actor_id).full_name if activity.actor_id in users else None,
            summary=activity.summary,
            detail=None,
            created_at=activity.created_at,
        )
        for activity in activities
    ]
    items.sort(key=lambda item: item.created_at, reverse=True)
    return items


def list_cases(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    status: list[CaseStatus] | None = None,
    priority: list[Priority] | None = None,
    assigned_user_id: uuid.UUID | None = None,
    search: str | None = None,
    tag: str | None = None,
    breached: bool | None = None,
    open_only: bool = False,
) -> tuple[list[CaseSummary], int]:
    stmt = select(Case).where(Case.org_id == org_id, Case.deleted_at.is_(None))
    if open_only:
        stmt = stmt.where(Case.status.in_([s for s in CaseStatus if s not in {CaseStatus.CLOSED, CaseStatus.CANCELLED}]))
    if status:
        stmt = stmt.where(Case.status.in_(status))
    if priority:
        stmt = stmt.where(Case.priority.in_(priority))
    if assigned_user_id:
        stmt = stmt.where(Case.assigned_user_id == assigned_user_id)
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(or_(func.lower(Case.title).like(pattern), func.lower(Case.case_number).like(pattern)))
    if tag:
        stmt = stmt.where(json_array_contains(db, Case.tags, tag))
    if breached:
        stmt = stmt.where(
            Case.due_at.is_not(None),
            Case.due_at < utcnow(),
            Case.status.notin_([CaseStatus.RESOLVED, CaseStatus.CLOSED, CaseStatus.CANCELLED]),
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_column = {
        "created_at": Case.created_at,
        "due_at": Case.due_at,
        "priority": Case.priority,
        "last_activity_at": Case.last_activity_at,
        "case_number": Case.case_number,
    }.get(pagination.sort or "last_activity_at", Case.last_activity_at)
    ordering = sort_column.asc() if pagination.order == "asc" else sort_column.desc()
    rows = db.scalars(stmt.order_by(ordering, Case.id).offset(pagination.offset).limit(pagination.page_size)).all()
    return _summaries(db, list(rows)), total
