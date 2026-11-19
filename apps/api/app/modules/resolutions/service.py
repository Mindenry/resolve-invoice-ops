"""Resolution proposal, approval request and audited execution."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.errors import AppError, BadRequestError, ConflictError, ForbiddenError, NotFoundError
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
from app.models.ai import ApprovalRequest, Resolution, ResolutionExecution
from app.models.cases import Case
from app.models.identity import Organization, User
from app.modules.cases.service import log_activity, transition
from app.modules.resolutions.actions import get_definition, validate_parameters
from app.modules.resolutions.policy import evaluate_policy
from app.modules.resolutions.schemas import ResolutionOut
from app.services.audit import record_audit
from app.services.events import emit_event
from app.services.notifications import notify, user_ids_with_permission

logger = get_logger(__name__)


def get_resolution(db: Session, *, org_id: uuid.UUID, resolution_id: uuid.UUID) -> Resolution:
    resolution = db.scalar(
        select(Resolution).where(Resolution.id == resolution_id, Resolution.org_id == org_id)
    )
    if resolution is None:
        raise NotFoundError("Resolution not found.", code="resolution_not_found")
    return resolution


def _idempotency_key(case_id: uuid.UUID, action_type: str, parameters: dict[str, Any]) -> str:
    material = json.dumps(
        {"case": str(case_id), "action": action_type, "parameters": parameters},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def create_resolution(
    db: Session,
    *,
    case: Case,
    actor_id: uuid.UUID | None,
    action_type: ActionType | str,
    description: str,
    parameters: dict[str, Any],
    evidence: list[dict[str, Any]],
    risk_level: RiskLevel | str | None = None,
    ai_model: str | None = None,
    prompt_version: str | None = None,
    investigation_id: uuid.UUID | None = None,
) -> Resolution:
    definition = get_definition(action_type)
    validated = validate_parameters(definition.action_type, parameters)
    parameters = validated.model_dump(mode="json")
    idempotency_key = _idempotency_key(case.id, definition.action_type.value, parameters)
    existing = db.scalar(
        select(Resolution).where(
            Resolution.org_id == case.org_id, Resolution.idempotency_key == idempotency_key
        )
    )
    if existing is not None:
        if existing.status in {
            ResolutionStatus.REJECTED,
            ResolutionStatus.CANCELLED,
            ResolutionStatus.EXPIRED,
        }:
            # Allow a genuinely new proposal after a terminal decision. The nonce keeps the
            # organization-wide unique idempotency key while status remains the audit source.
            idempotency_key = f"{idempotency_key}:{uuid.uuid4().hex[:12]}"
        else:
            return existing

    organization = db.get(Organization, case.org_id)
    requested_risk = RiskLevel(risk_level) if risk_level else definition.default_risk
    policy = evaluate_policy(
        definition=definition,
        requested_risk=requested_risk,
        org_settings=dict(organization.settings) if organization else {},
    )
    resolution = Resolution(
        org_id=case.org_id,
        case_id=case.id,
        investigation_id=investigation_id,
        action_type=definition.action_type,
        description=description[:4000],
        parameters=parameters,
        supporting_evidence=evidence or [],
        risk_level=policy.risk_level,
        expected_outcome=definition.description,
        required_permissions=list(definition.required_permissions),
        requires_approval=policy.requires_approval,
        status=ResolutionStatus.VALIDATED,
        idempotency_key=idempotency_key,
        created_by_id=actor_id,
        ai_model=ai_model,
        prompt_version=prompt_version,
    )
    db.add(resolution)
    db.flush()
    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="RESOLUTION_PROPOSED",
        summary=f"Resolution proposed: {definition.label}",
        payload={
            "resolution_id": str(resolution.id),
            "risk": policy.risk_level.value,
            "requires_approval": policy.requires_approval,
            "policy_reasons": policy.reasons,
        },
    )
    record_audit(
        db,
        org_id=case.org_id,
        action="resolution.proposed",
        entity_type="resolution",
        entity_id=resolution.id,
        summary=f"{definition.label} proposed for {case.case_number}",
        actor_id=actor_id,
        after={
            "action_type": definition.action_type.value,
            "risk": policy.risk_level.value,
            "requires_approval": policy.requires_approval,
        },
    )
    emit_event(
        db,
        org_id=case.org_id,
        event_type=EventType.RESOLUTION_PROPOSED,
        entity_type="CASE",
        entity_id=case.id,
        payload={"resolution_id": str(resolution.id), "action_type": definition.action_type.value},
    )
    return resolution


def _assert_valid_approver(db: Session, *, org_id: uuid.UUID, user_id: uuid.UUID | None) -> None:
    """An assigned approver must be an active member who can actually decide."""
    if user_id is None:
        return
    from app.models.identity import Membership, Role
    from app.modules.auth.service import permissions_for_role

    user = db.get(User, user_id)
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == user_id,
            Membership.org_id == org_id,
            Membership.is_active.is_(True),
        )
    )
    if user is None or not user.is_active or membership is None:
        raise BadRequestError(
            "The assigned approver must be an active member of the organization.",
            code="invalid_approver",
        )
    role = db.get(Role, membership.role_id)
    if role is None or "approval:decide" not in permissions_for_role(db, role.id):
        raise BadRequestError(
            "The assigned approver does not have permission to decide approvals.",
            code="approver_lacks_permission",
        )


def request_approval(
    db: Session,
    *,
    resolution: Resolution,
    requester_id: uuid.UUID,
    approver_role: str | None = None,
    assigned_approver_id: uuid.UUID | None = None,
    note: str | None = None,
) -> ApprovalRequest:
    if resolution.status == ResolutionStatus.COMPLETED:
        raise ConflictError("This resolution has already been executed.", code="resolution_completed")
    if resolution.status == ResolutionStatus.REJECTED:
        raise BadRequestError("Rejected resolutions cannot be resubmitted.", code="resolution_rejected")
    _assert_valid_approver(db, org_id=resolution.org_id, user_id=assigned_approver_id)
    existing = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.resolution_id == resolution.id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
    )
    if existing is not None:
        return existing
    policy = evaluate_policy(
        definition=get_definition(resolution.action_type),
        requested_risk=resolution.risk_level,
        org_settings=dict(db.get(Organization, resolution.org_id).settings or {}),
    )
    from app.config.settings import settings

    approval = ApprovalRequest(
        org_id=resolution.org_id,
        case_id=resolution.case_id,
        resolution_id=resolution.id,
        action_type=resolution.action_type,
        title=f"Approve: {get_definition(resolution.action_type).label}",
        requester_id=requester_id,
        approver_role=approver_role or policy.approver_role,
        assigned_approver_id=assigned_approver_id,
        risk_level=resolution.risk_level,
        status=ApprovalStatus.PENDING,
        evidence=resolution.supporting_evidence or [],
        parameters=resolution.parameters,
        expires_at=utcnow() + timedelta(hours=settings.APPROVAL_EXPIRY_HOURS),
    )
    db.add(approval)
    db.flush()
    resolution.status = ResolutionStatus.AWAITING_APPROVAL
    case = db.get(Case, resolution.case_id)
    if case is not None and case.status in {CaseStatus.OPEN, CaseStatus.INVESTIGATING, CaseStatus.REOPENED}:
        transition(
            db,
            case=case,
            new_status=CaseStatus.AWAITING_APPROVAL,
            actor_id=requester_id,
            note="Awaiting approval for proposed resolution",
        )
    record_audit(
        db,
        org_id=resolution.org_id,
        action="approval.requested",
        entity_type="resolution",
        entity_id=resolution.id,
        summary=f"Approval requested for {resolution.action_type.value}",
        actor_id=requester_id,
        after={
            "approval_id": str(approval.id),
            "risk": resolution.risk_level.value,
            "approver_role": approval.approver_role,
            "assigned_approver_id": str(assigned_approver_id) if assigned_approver_id else None,
        },
    )
    emit_event(
        db,
        org_id=resolution.org_id,
        event_type=EventType.APPROVAL_REQUESTED,
        entity_type="CASE",
        entity_id=resolution.case_id,
        payload={"approval_id": str(approval.id), "resolution_id": str(resolution.id)},
    )
    recipients = (
        [assigned_approver_id]
        if assigned_approver_id
        else user_ids_with_permission(db, org_id=resolution.org_id, permission="approval:decide")
    )
    for user_id in recipients:
        if user_id == requester_id and not policy.allow_self_approval:
            continue
        notify(
            db,
            org_id=resolution.org_id,
            user_id=user_id,
            type=NotificationType.APPROVAL_REQUIRED,
            title=approval.title,
            body=(note or resolution.description)[:500],
            entity_type="APPROVAL",
            entity_id=approval.id,
            send_mail=True,
        )
    return approval


def _assert_permissions(resolution: Resolution, permissions: set[str]) -> None:
    missing = [permission for permission in resolution.required_permissions if permission not in permissions]
    if missing:
        raise ForbiddenError(
            "You do not hold the permissions required to execute this action.",
            code="missing_action_permission",
            details={"missing": missing},
        )


def execute_resolution(
    db: Session, *, resolution: Resolution, actor_id: uuid.UUID, permissions: set[str]
) -> Resolution:
    if resolution.status == ResolutionStatus.COMPLETED:
        return resolution
    if resolution.status in {ResolutionStatus.CANCELLED, ResolutionStatus.REJECTED, ResolutionStatus.EXPIRED}:
        raise BadRequestError(
            f"A resolution in status {resolution.status.value} cannot be executed.",
            code="resolution_not_executable",
        )
    if resolution.requires_approval and resolution.status != ResolutionStatus.APPROVED:
        raise BadRequestError(
            "This action requires an approved approval request before execution.",
            code="approval_required",
        )
    if not resolution.requires_approval and resolution.status not in {
        ResolutionStatus.VALIDATED,
        ResolutionStatus.PROPOSED,
        ResolutionStatus.APPROVED,
    }:
        raise BadRequestError(
            f"A resolution in status {resolution.status.value} cannot be executed.",
            code="resolution_not_executable",
        )
    _assert_permissions(resolution, permissions)
    definition = get_definition(resolution.action_type)
    validate_parameters(resolution.action_type, resolution.parameters)

    attempt = (
        db.scalar(
            select(func.count())
            .select_from(ResolutionExecution)
            .where(ResolutionExecution.resolution_id == resolution.id)
        )
        or 0
    ) + 1
    execution = ResolutionExecution(
        resolution_id=resolution.id,
        attempt=attempt,
        status="RUNNING",
        actor_id=actor_id,
        started_at=utcnow(),
    )
    db.add(execution)
    resolution.status = ResolutionStatus.EXECUTING
    db.flush()

    try:
        result = definition.executor(db, resolution, actor_id)
    except Exception as exc:  # noqa: BLE001 - execution failures are persisted and surfaced
        logger.exception("resolution_execution_failed", resolution_id=str(resolution.id))
        resolution.status = ResolutionStatus.FAILED
        resolution.error = f"{type(exc).__name__}: {exc}"[:2000]
        execution.status = "FAILED"
        execution.error = resolution.error
        execution.finished_at = utcnow()
        record_audit(
            db,
            org_id=resolution.org_id,
            action="resolution.failed",
            entity_type="resolution",
            entity_id=resolution.id,
            summary=f"Execution failed: {resolution.error}",
            actor_id=actor_id,
        )
        return resolution

    resolution.status = ResolutionStatus.COMPLETED
    resolution.execution_result = result
    resolution.executed_at = utcnow()
    resolution.executed_by_id = actor_id
    resolution.error = None
    execution.status = "SUCCEEDED"
    execution.result = result
    execution.finished_at = utcnow()
    case = db.get(Case, resolution.case_id)
    if case is not None:
        log_activity(
            db,
            case=case,
            actor_id=actor_id,
            activity_type="RESOLUTION_EXECUTED",
            summary=f"Executed: {get_definition(resolution.action_type).label}",
            payload={"resolution_id": str(resolution.id), "result": result},
        )
        if case.status == CaseStatus.AWAITING_APPROVAL:
            transition(
                db,
                case=case,
                new_status=CaseStatus.RESOLUTION_IN_PROGRESS,
                actor_id=actor_id,
                note="Resolution executed",
            )
    record_audit(
        db,
        org_id=resolution.org_id,
        action="resolution.executed",
        entity_type="resolution",
        entity_id=resolution.id,
        summary=f"{resolution.action_type.value} executed successfully",
        actor_id=actor_id,
        after={"attempt": attempt, "result": result},
    )
    emit_event(
        db,
        org_id=resolution.org_id,
        event_type=EventType.RESOLUTION_EXECUTED,
        entity_type="CASE",
        entity_id=resolution.case_id,
        payload={"resolution_id": str(resolution.id), "action_type": resolution.action_type.value},
    )
    return resolution


def execute_resolution_job(resolution_id: uuid.UUID, org_id: uuid.UUID) -> dict[str, Any]:
    from app.db.session import session_scope
    from app.models.identity import Membership
    from app.modules.auth.service import permissions_for_role

    with session_scope() as db:
        resolution = db.scalar(
            select(Resolution).where(Resolution.id == resolution_id, Resolution.org_id == org_id)
        )
        if resolution is None:
            return {"status": "skipped", "reason": "resolution_not_found"}
        actor_id = resolution.executed_by_id or resolution.created_by_id
        if actor_id is None:
            return {"status": "failed", "reason": "no_actor"}
        membership = db.scalar(select(Membership).where(Membership.user_id == actor_id, Membership.org_id == org_id))
        permissions: set[str] = set()
        if membership is not None:
            permissions = set(permissions_for_role(db, membership.role_id))
        execute_resolution(db, resolution=resolution, actor_id=actor_id, permissions=permissions)
        return {"status": resolution.status.value, "resolution_id": str(resolution.id), "error": resolution.error}


def cancel_resolution(
    db: Session, *, resolution: Resolution, actor_id: uuid.UUID, reason: str | None
) -> Resolution:
    if resolution.status in {ResolutionStatus.COMPLETED, ResolutionStatus.CANCELLED}:
        raise BadRequestError("The resolution cannot be cancelled.", code="resolution_not_cancellable")
    resolution.status = ResolutionStatus.CANCELLED
    resolution.error = reason
    approval = db.scalar(
        select(ApprovalRequest).where(
            ApprovalRequest.resolution_id == resolution.id,
            ApprovalRequest.status == ApprovalStatus.PENDING,
        )
    )
    if approval is not None:
        approval.status = ApprovalStatus.CANCELLED
        approval.decided_at = utcnow()
        approval.decision_note = reason
    record_audit(
        db,
        org_id=resolution.org_id,
        action="resolution.cancelled",
        entity_type="resolution",
        entity_id=resolution.id,
        summary="Resolution cancelled",
        actor_id=actor_id,
        context={"reason": reason},
    )
    return resolution


def retry_execution(
    db: Session, *, resolution: Resolution, actor_id: uuid.UUID, permissions: set[str]
) -> Resolution:
    if resolution.status != ResolutionStatus.FAILED:
        raise BadRequestError("Only failed resolutions can be retried.", code="resolution_not_failed")
    resolution.status = ResolutionStatus.APPROVED if resolution.requires_approval else ResolutionStatus.VALIDATED
    resolution.error = None
    return execute_resolution(db, resolution=resolution, actor_id=actor_id, permissions=permissions)


def resolution_out(db: Session, resolution: Resolution) -> ResolutionOut:
    case = db.get(Case, resolution.case_id)
    creator = db.get(User, resolution.created_by_id) if resolution.created_by_id else None
    approval = db.scalar(
        select(ApprovalRequest)
        .where(ApprovalRequest.resolution_id == resolution.id)
        .order_by(ApprovalRequest.created_at.desc())
        .limit(1)
    )
    executions = db.scalars(
        select(ResolutionExecution)
        .where(ResolutionExecution.resolution_id == resolution.id)
        .order_by(ResolutionExecution.started_at.desc())
    ).all()
    return ResolutionOut(
        id=resolution.id,
        case_id=resolution.case_id,
        case_number=case.case_number if case else None,
        investigation_id=resolution.investigation_id,
        action_type=resolution.action_type,
        description=resolution.description,
        parameters=resolution.parameters,
        supporting_evidence=resolution.supporting_evidence or [],
        risk_level=resolution.risk_level,
        expected_outcome=resolution.expected_outcome,
        required_permissions=resolution.required_permissions or [],
        requires_approval=resolution.requires_approval,
        status=resolution.status,
        created_by_id=resolution.created_by_id,
        created_by_name=creator.full_name if creator else None,
        ai_model=resolution.ai_model,
        prompt_version=resolution.prompt_version,
        execution_result=resolution.execution_result,
        error=resolution.error,
        executed_at=resolution.executed_at,
        created_at=resolution.created_at,
        approval={
            "id": str(approval.id),
            "status": approval.status.value,
            "approver_role": approval.approver_role,
            "assigned_approver_id": str(approval.assigned_approver_id) if approval.assigned_approver_id else None,
            "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        }
        if approval
        else None,
        executions=[
            {
                "id": str(item.id),
                "attempt": item.attempt,
                "status": item.status,
                "error": item.error,
                "started_at": item.started_at.isoformat() if item.started_at else None,
                "finished_at": item.finished_at.isoformat() if item.finished_at else None,
            }
            for item in executions
        ],
    )


def list_resolutions(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    case_id: uuid.UUID | None = None,
    status: list[ResolutionStatus] | None = None,
    action_type: ActionType | None = None,
) -> tuple[list[Resolution], int]:
    stmt = select(Resolution).where(Resolution.org_id == org_id)
    if case_id:
        stmt = stmt.where(Resolution.case_id == case_id)
    if status:
        stmt = stmt.where(Resolution.status.in_(status))
    if action_type:
        stmt = stmt.where(Resolution.action_type == action_type)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Resolution.created_at.desc()).offset(pagination.offset).limit(pagination.page_size)
    ).all()
    return list(rows), total


def ensure_approval_request(
    db: Session, *, case: Case, actor_id: uuid.UUID, payload: Any
) -> ApprovalRequest:
    from app.modules.approvals.service import create_manual_request

    return create_manual_request(db, case=case, actor_id=actor_id, payload=payload)


__all__ = [
    "AppError",
    "RiskLevel",
    "RoleCode",
    "create_resolution",
    "execute_resolution",
    "execute_resolution_job",
    "get_resolution",
    "list_resolutions",
    "request_approval",
    "resolution_out",
]
