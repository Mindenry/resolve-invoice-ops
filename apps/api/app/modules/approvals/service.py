"""Human-in-the-loop approval decisions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.core.errors import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.logging import get_logger
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.domain.enums import (
    ActionType,
    ApprovalStatus,
    CaseStatus,
    EventType,
    NotificationType,
    ResolutionStatus,
    RiskLevel,
    RoleCode,
)
from app.models.ai import ApprovalDecision, ApprovalRequest, Resolution
from app.models.cases import Case
from app.models.identity import Membership, Organization, Role, User
from app.modules.approvals.schemas import (
    ApprovalDecisionRecord,
    ApprovalDetail,
    ApprovalOut,
    ApprovalStats,
)
from app.modules.cases.service import log_activity, transition
from app.modules.resolutions.actions import get_definition
from app.modules.resolutions.service import _assert_valid_approver, execute_resolution
from app.services.audit import record_audit
from app.services.events import emit_event
from app.services.notifications import notify, user_ids_with_permission

logger = get_logger(__name__)


def _as_aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def get_approval(db: Session, *, org_id: uuid.UUID, approval_id: uuid.UUID) -> ApprovalRequest:
    approval = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.id == approval_id, ApprovalRequest.org_id == org_id
        )
    )
    if approval is None:
        raise NotFoundError("Approval request not found.", code="approval_not_found")
    return approval


def _ensure_pending(approval: ApprovalRequest) -> None:
    if approval.status != ApprovalStatus.PENDING:
        raise ConflictError(
            f"This approval request is already {approval.status.value.lower()}.",
            code="approval_not_pending",
        )
    expires_at = _as_aware(approval.expires_at)
    if expires_at is not None and expires_at <= utcnow():
        approval.status = ApprovalStatus.EXPIRED
        raise ConflictError("This approval request has expired.", code="approval_expired")


def _self_approval_allowed(db: Session, approval: ApprovalRequest) -> bool:
    organization = db.get(Organization, approval.org_id)
    policy = (organization.settings or {}).get("approval_policy", {}) if organization else {}
    return bool(policy.get("allow_self_approval", settings.ALLOW_SELF_APPROVAL))


def _assert_can_decide(
    db: Session, *, approval: ApprovalRequest, actor: User, permissions: set[str], is_superadmin: bool = False
) -> None:
    if "approval:decide" not in permissions and not is_superadmin:
        raise ForbiddenError("You do not have permission to decide approvals.", code="missing_permission")
    if approval.assigned_approver_id is not None and approval.assigned_approver_id != actor.id and not is_superadmin:
        raise ForbiddenError(
            "This approval is assigned to a different approver.", code="approval_assigned_elsewhere"
        )
    if approval.requester_id == actor.id and not _self_approval_allowed(db, approval):
        raise ForbiddenError(
            "You cannot approve your own request under the current policy.", code="self_approval_denied"
        )


def _approval_out(
    db: Session, approval: ApprovalRequest, *, viewer_id: uuid.UUID, viewer_permissions: set[str], is_superadmin: bool
) -> ApprovalOut:
    case = db.get(Case, approval.case_id)
    requester = db.get(User, approval.requester_id) if approval.requester_id else None
    assigned = db.get(User, approval.assigned_approver_id) if approval.assigned_approver_id else None
    decided_by = db.get(User, approval.decided_by_id) if approval.decided_by_id else None
    resolution = db.get(Resolution, approval.resolution_id) if approval.resolution_id else None
    expires_at = _as_aware(approval.expires_at)
    overdue = bool(
        approval.status == ApprovalStatus.PENDING and expires_at is not None and expires_at <= utcnow()
    )
    can_decide = approval.status == ApprovalStatus.PENDING and "approval:decide" in viewer_permissions
    if approval.assigned_approver_id and approval.assigned_approver_id != viewer_id and not is_superadmin:
        can_decide = False
    if approval.requester_id == viewer_id and not _self_approval_allowed(db, approval):
        can_decide = False
    return ApprovalOut(
        id=approval.id,
        case_id=approval.case_id,
        case_number=case.case_number if case else None,
        case_title=case.title if case else None,
        resolution_id=approval.resolution_id,
        resolution_status=resolution.status if resolution else None,
        action_type=approval.action_type,
        title=approval.title,
        description=resolution.description if resolution else "",
        requester={"id": requester.id, "full_name": requester.full_name, "email": requester.email} if requester else None,
        approver_role=approval.approver_role,
        assigned_approver={"id": assigned.id, "full_name": assigned.full_name, "email": assigned.email}
        if assigned
        else None,
        risk_level=approval.risk_level,
        status=approval.status,
        evidence=approval.evidence or [],
        parameters=approval.parameters or {},
        expires_at=approval.expires_at,
        overdue=overdue,
        decided_at=approval.decided_at,
        decided_by={"id": decided_by.id, "full_name": decided_by.full_name, "email": decided_by.email}
        if decided_by
        else None,
        decision_note=approval.decision_note,
        created_at=approval.created_at,
        can_decide=can_decide,
    )


def create_manual_request(db: Session, *, case: Case, actor_id: uuid.UUID, payload: Any) -> ApprovalRequest:
    _assert_valid_approver(db, org_id=case.org_id, user_id=payload.approver_id)
    approval = ApprovalRequest(
        org_id=case.org_id,
        case_id=case.id,
        resolution_id=None,
        action_type=payload.action_type,
        title=payload.title,
        requester_id=actor_id,
        approver_role=RoleCode.OPERATIONS_MANAGER.value
        if payload.risk_level in {RiskLevel.LOW, RiskLevel.MEDIUM}
        else RoleCode.ORG_ADMIN.value,
        assigned_approver_id=payload.approver_id,
        risk_level=payload.risk_level,
        status=ApprovalStatus.PENDING,
        evidence=payload.evidence,
        parameters=payload.parameters,
        expires_at=utcnow() + timedelta(hours=settings.APPROVAL_EXPIRY_HOURS),
    )
    db.add(approval)
    db.flush()
    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="APPROVAL_REQUESTED",
        summary=f"Approval requested: {payload.title}",
        payload={"approval_id": str(approval.id), "risk": payload.risk_level.value},
    )
    record_audit(
        db,
        org_id=case.org_id,
        action="approval.requested",
        entity_type="approval",
        entity_id=approval.id,
        summary=payload.title,
        actor_id=actor_id,
        after={"risk": payload.risk_level.value, "approver_id": str(payload.approver_id) if payload.approver_id else None},
    )
    emit_event(
        db,
        org_id=case.org_id,
        event_type=EventType.APPROVAL_REQUESTED,
        entity_type="CASE",
        entity_id=case.id,
        payload={"approval_id": str(approval.id), "title": payload.title},
    )
    recipients = (
        [payload.approver_id]
        if payload.approver_id
        else user_ids_with_permission(db, org_id=case.org_id, permission="approval:decide")
    )
    for user_id in recipients:
        if user_id == actor_id:
            continue
        notify(
            db,
            org_id=case.org_id,
            user_id=user_id,
            type=NotificationType.APPROVAL_REQUIRED,
            title=f"Approval required: {payload.title}",
            body=(payload.note or f"Case {case.case_number}")[:500],
            entity_type="APPROVAL",
            entity_id=approval.id,
            send_mail=True,
        )
    return approval


def list_approvals(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    status: list[ApprovalStatus] | None = None,
    risk: RiskLevel | None = None,
    mine: bool = False,
    viewer_id: uuid.UUID,
    viewer_permissions: set[str],
    is_superadmin: bool = False,
) -> tuple[list[ApprovalOut], int]:
    stmt = select(ApprovalRequest).where(ApprovalRequest.org_id == org_id)
    if status:
        stmt = stmt.where(ApprovalRequest.status.in_(status))
    if risk:
        stmt = stmt.where(ApprovalRequest.risk_level == risk)
    if mine:
        stmt = stmt.where(
            (ApprovalRequest.requester_id == viewer_id) | (ApprovalRequest.assigned_approver_id == viewer_id)
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(
            ApprovalRequest.status == ApprovalStatus.PENDING,
            ApprovalRequest.created_at.desc(),
        )
        .offset(pagination.offset)
        .limit(pagination.page_size)
    ).all()
    return [
        _approval_out(
            db, row, viewer_id=viewer_id, viewer_permissions=viewer_permissions, is_superadmin=is_superadmin
        )
        for row in rows
    ], total


def detail(
    db: Session,
    *,
    approval: ApprovalRequest,
    viewer_id: uuid.UUID,
    viewer_permissions: set[str],
    is_superadmin: bool = False,
) -> ApprovalDetail:
    base = _approval_out(
        db, approval, viewer_id=viewer_id, viewer_permissions=viewer_permissions, is_superadmin=is_superadmin
    )
    decisions = db.scalars(
        select(ApprovalDecision)
        .where(ApprovalDecision.request_id == approval.id)
        .order_by(ApprovalDecision.created_at.desc())
    ).all()
    users = {
        user.id: user
        for user in db.scalars(
            select(User).where(User.id.in_([d.decided_by_id for d in decisions if d.decided_by_id]))
        ).all()
    } if decisions else {}
    resolution = db.get(Resolution, approval.resolution_id) if approval.resolution_id else None
    return ApprovalDetail(
        **base.model_dump(),
        resolution={
            "id": str(resolution.id),
            "action_type": resolution.action_type.value,
            "status": resolution.status.value,
            "description": resolution.description,
            "parameters": resolution.parameters,
            "required_permissions": resolution.required_permissions,
            "execution_result": resolution.execution_result,
            "error": resolution.error,
        }
        if resolution
        else None,
        decisions=[
            ApprovalDecisionRecord(
                id=decision.id,
                decision=decision.decision,
                decided_by_name=users.get(decision.decided_by_id).full_name
                if decision.decided_by_id in users
                else None,
                comment=decision.comment,
                created_at=decision.created_at,
            )
            for decision in decisions
        ],
    )


def decide(
    db: Session,
    *,
    approval: ApprovalRequest,
    actor: User,
    permissions: set[str],
    is_superadmin: bool,
    approve: bool,
    comment: str | None,
    execute_after_approval: bool = False,
) -> tuple[ApprovalRequest, str | None]:
    _ensure_pending(approval)
    _assert_can_decide(db, approval=approval, actor=actor, permissions=permissions, is_superadmin=is_superadmin)
    if not approve and not comment:
        raise BadRequestError("A rejection reason is required.", code="rejection_reason_required")
    now = utcnow()
    decision_value = "APPROVED" if approve else "REJECTED"
    approval.status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
    approval.decided_at = now
    approval.decided_by_id = actor.id
    approval.decision_note = comment
    db.add(
        ApprovalDecision(
            request_id=approval.id,
            decision=decision_value,
            decided_by_id=actor.id,
            comment=comment,
        )
    )
    execution_error: str | None = None
    resolution = db.get(Resolution, approval.resolution_id) if approval.resolution_id else None
    if resolution is not None:
        if approve:
            resolution.status = ResolutionStatus.APPROVED
            if execute_after_approval:
                if "resolution:execute" not in permissions and not is_superadmin:
                    execution_error = "You can approve but not execute this action."
                else:
                    resolution = execute_resolution(
                        db,
                        resolution=resolution,
                        actor_id=actor.id,
                        permissions=set(permissions) if not is_superadmin else set(permissions) | {"resolution:execute"},
                    )
                    if resolution.status == ResolutionStatus.FAILED:
                        execution_error = resolution.error
        else:
            resolution.status = ResolutionStatus.REJECTED
    case = db.get(Case, approval.case_id)
    if case is not None:
        log_activity(
            db,
            case=case,
            actor_id=actor.id,
            activity_type=f"APPROVAL_{decision_value}",
            summary=f"Approval {decision_value.lower()}: {approval.title}",
            payload={"approval_id": str(approval.id), "comment": comment, "execution_error": execution_error},
        )
        if case.status == CaseStatus.AWAITING_APPROVAL:
            target = CaseStatus.RESOLUTION_IN_PROGRESS if approve else CaseStatus.INVESTIGATING
            try:
                transition(
                    db,
                    case=case,
                    new_status=target,
                    actor_id=actor.id,
                    note=f"Approval {decision_value.lower()}",
                )
            except Exception:  # noqa: BLE001 - transition is best-effort after a decision
                logger.info("approval_case_transition_skipped", case_id=str(case.id), status=case.status.value)
    record_audit(
        db,
        org_id=approval.org_id,
        action="approval.decided",
        entity_type="approval",
        entity_id=approval.id,
        summary=f"Approval {decision_value.lower()} by {actor.email}",
        actor=actor,
        after={"decision": decision_value, "comment": comment, "resolution_id": str(approval.resolution_id) if approval.resolution_id else None},
    )
    emit_event(
        db,
        org_id=approval.org_id,
        event_type=EventType.APPROVAL_DECIDED,
        entity_type="CASE",
        entity_id=approval.case_id,
        payload={"approval_id": str(approval.id), "decision": decision_value, "resolution_status": resolution.status.value if resolution else None},
    )
    if approval.requester_id:
        notify(
            db,
            org_id=approval.org_id,
            user_id=approval.requester_id,
            type=NotificationType.APPROVAL_COMPLETED,
            title=f"Approval {decision_value.lower()}: {approval.title}",
            body=(comment or "")[:500],
            entity_type="APPROVAL",
            entity_id=approval.id,
            send_mail=True,
        )
    return approval, execution_error


def expire_overdue(org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope

    expired = 0
    with session_scope() as db:
        now = utcnow()
        rows = db.scalars(
            select(ApprovalRequest).where(
                ApprovalRequest.org_id == org_id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
                ApprovalRequest.expires_at.is_not(None),
            )
        ).all()
        for approval in rows:
            expires_at = _as_aware(approval.expires_at)
            if expires_at is not None and expires_at <= now:
                approval.status = ApprovalStatus.EXPIRED
                approval.decided_at = now
                approval.decision_note = "Expired automatically"
                expired += 1
                resolution = db.get(Resolution, approval.resolution_id) if approval.resolution_id else None
                if resolution is not None and resolution.status == ResolutionStatus.AWAITING_APPROVAL:
                    resolution.status = ResolutionStatus.EXPIRED
                record_audit(
                    db,
                    org_id=org_id,
                    action="approval.expired",
                    entity_type="approval",
                    entity_id=approval.id,
                    summary=f"Approval expired: {approval.title}",
                )
        return {"expired": expired}


def stats(db: Session, *, org_id: uuid.UUID) -> ApprovalStats:
    now = utcnow()
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    pending = db.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(ApprovalRequest.org_id == org_id, ApprovalRequest.status == ApprovalStatus.PENDING)
    ) or 0
    overdue = 0
    for approval in db.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.org_id == org_id, ApprovalRequest.status == ApprovalStatus.PENDING
        )
    ):
        expires_at = _as_aware(approval.expires_at)
        if expires_at is not None and expires_at <= now:
            overdue += 1
    approved_today = db.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(
            ApprovalRequest.org_id == org_id,
            ApprovalRequest.status == ApprovalStatus.APPROVED,
            ApprovalRequest.decided_at >= start_of_day,
        )
    ) or 0
    rejected_today = db.scalar(
        select(func.count())
        .select_from(ApprovalRequest)
        .where(
            ApprovalRequest.org_id == org_id,
            ApprovalRequest.status == ApprovalStatus.REJECTED,
            ApprovalRequest.decided_at >= start_of_day,
        )
    ) or 0
    decided = db.scalars(
        select(ApprovalRequest).where(
            ApprovalRequest.org_id == org_id, ApprovalRequest.decided_at.is_not(None)
        )
    ).all()
    durations = []
    for approval in decided:
        created = _as_aware(approval.created_at)
        decided_at = _as_aware(approval.decided_at)
        if created and decided_at:
            durations.append((decided_at - created).total_seconds() / 3600)
    rows = db.execute(
        select(ApprovalRequest.risk_level, func.count())
        .where(ApprovalRequest.org_id == org_id, ApprovalRequest.status == ApprovalStatus.PENDING)
        .group_by(ApprovalRequest.risk_level)
    ).all()
    return ApprovalStats(
        pending=int(pending),
        overdue=overdue,
        approved_today=int(approved_today),
        rejected_today=int(rejected_today),
        average_decision_hours=round(sum(durations) / len(durations), 2) if durations else 0.0,
        by_risk={risk.value: int(count) for risk, count in rows},
    )


def can_user_approve(db: Session, approval: ApprovalRequest, user_id: uuid.UUID) -> bool:
    actor = db.get(User, user_id)
    if actor is None:
        return False
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.org_id == approval.org_id,
            Membership.is_active.is_(True),
        )
    )
    if membership is None:
        return False
    role = db.get(Role, membership.role_id)
    if role is None:
        return False
    from app.modules.auth.service import permissions_for_role

    permissions = set(permissions_for_role(db, role.id))
    try:
        _assert_can_decide(db, approval=approval, actor=actor, permissions=permissions)
    except ForbiddenError:
        return False
    return True


def action_label(action_type: ActionType) -> str:
    try:
        return get_definition(action_type).label
    except Exception:  # noqa: BLE001
        return action_type.value


# `action_label` keeps action names consistent in notifications from other modules.
__all__ = [
    "action_label",
    "can_user_approve",
    "create_manual_request",
    "decide",
    "detail",
    "expire_overdue",
    "get_approval",
    "list_approvals",
    "stats",
]
