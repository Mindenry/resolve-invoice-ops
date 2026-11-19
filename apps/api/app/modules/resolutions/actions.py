"""Allow-listed resolution actions with typed parameters and real executors.

An action can only run if it is registered here, its parameters validate, the actor holds
every required permission, and (where required) an approval has been granted.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, NotFoundError, UnprocessableError
from app.core.logging import get_logger
from app.core.security import utcnow
from app.domain.enums import (
    ActionType,
    CaseStatus,
    ExceptionStatus,
    InvoiceStatus,
    NotificationType,
    Priority,
    RiskLevel,
)
from app.models.ai import Resolution
from app.models.cases import Case, ExceptionRecord
from app.models.finance import Invoice, Vendor
from app.services.email import send_email
from app.services.notifications import notify, user_ids_with_permission

logger = get_logger(__name__)


class VendorConfirmationParams(BaseModel):
    vendor_id: uuid.UUID
    invoice_id: uuid.UUID | None = None
    message: str | None = Field(default=None, max_length=2000)


class MissingDocumentsParams(BaseModel):
    vendor_id: uuid.UUID
    requested_items: list[str] = Field(min_length=1, max_length=20)
    message: str | None = Field(default=None, max_length=2000)


class PriorityParams(BaseModel):
    priority: Priority


class AssignParams(BaseModel):
    user_id: uuid.UUID
    reason: str | None = Field(default=None, max_length=255)


class RetryIntegrationParams(BaseModel):
    integration_id: uuid.UUID


class RetryJobParams(BaseModel):
    job_id: uuid.UUID


class EmailDraftParams(BaseModel):
    to: EmailStr
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=8000)


class NotifyTeamParams(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class MarkDuplicateParams(BaseModel):
    invoice_id: uuid.UUID
    duplicate_invoice_id: uuid.UUID
    note: str = Field(min_length=3, max_length=2000)


class EscalateParams(BaseModel):
    reason: str = Field(min_length=3, max_length=1000)
    priority: Priority = Priority.URGENT


class NoParams(BaseModel):
    pass


@dataclass(frozen=True, slots=True)
class ActionDefinition:
    action_type: ActionType
    label: str
    description: str
    parameters_model: type[BaseModel]
    required_permissions: tuple[str, ...]
    default_risk: RiskLevel
    external_side_effect: bool
    financial_impact: bool
    executor: Callable[[Session, Resolution, uuid.UUID | None], dict[str, Any]]
    policy_notes: str = ""
    display_order: int = field(default=100)


def _case_or_404(db: Session, resolution: Resolution) -> Case:
    case = db.get(Case, resolution.case_id)
    if case is None or case.org_id != resolution.org_id:
        raise NotFoundError("Case not found.", code="case_not_found")
    return case


def _vendor_or_404(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(
            Vendor.id == vendor_id, Vendor.org_id == org_id, Vendor.deleted_at.is_(None)
        )
    )
    if vendor is None:
        raise NotFoundError("Vendor not found.", code="vendor_not_found")
    return vendor


def _activity(db: Session, case: Case, actor_id: uuid.UUID | None, summary: str, payload: dict[str, Any]) -> None:
    from app.modules.cases.service import log_activity

    log_activity(
        db,
        case=case,
        actor_id=actor_id,
        activity_type="RESOLUTION_EXECUTED",
        summary=summary,
        payload=payload,
    )


def execute_vendor_confirmation(
    db: Session, resolution: Resolution, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    params = VendorConfirmationParams.model_validate(resolution.parameters)
    vendor = _vendor_or_404(db, resolution.org_id, params.vendor_id)
    if not vendor.email:
        raise UnprocessableError(
            "The vendor has no contact email; add one before requesting confirmation.",
            code="vendor_email_missing",
        )
    case = _case_or_404(db, resolution)
    subject = f"Confirmation required: invoice query ({case.case_number})"
    body = params.message or (
        f"Hello {vendor.contact_name or vendor.legal_name},\n\n"
        f"We are reconciling an invoice and need your confirmation.\n\n"
        f"Reference: {case.case_number}\n{resolution.description}\n\n"
        "Please reply with the corrected documents or a confirmation of the details.\n"
    )
    delivery = send_email(to=vendor.email, subject=subject, body=body)
    _activity(db, case, actor_id, f"Vendor confirmation requested from {vendor.legal_name}", {"email": vendor.email})
    return {"email_to": vendor.email, "subject": subject, **delivery}


def execute_request_missing_documents(
    db: Session, resolution: Resolution, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    params = MissingDocumentsParams.model_validate(resolution.parameters)
    vendor = _vendor_or_404(db, resolution.org_id, params.vendor_id)
    if not vendor.email:
        raise UnprocessableError("The vendor has no contact email.", code="vendor_email_missing")
    case = _case_or_404(db, resolution)
    items = "\n".join(f"- {item}" for item in params.requested_items)
    subject = f"Missing documents request ({case.case_number})"
    body = params.message or (
        f"Hello {vendor.contact_name or vendor.legal_name},\n\n"
        f"To continue processing, please provide:\n{items}\n\n"
        f"Reference: {case.case_number}\n"
    )
    delivery = send_email(to=vendor.email, subject=subject, body=body)
    from app.modules.cases.service import transition

    if case.status in {CaseStatus.OPEN, CaseStatus.INVESTIGATING, CaseStatus.REOPENED}:
        transition(
            db,
            case=case,
            new_status=CaseStatus.AWAITING_INFORMATION,
            actor_id=actor_id,
            note="Missing documents requested from vendor",
        )
    _activity(db, case, actor_id, "Requested missing documents from vendor", {"items": params.requested_items})
    return {
        "email_to": vendor.email,
        "requested_items": params.requested_items,
        **delivery,
    }


def execute_update_priority(
    db: Session, resolution: Resolution, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    params = PriorityParams.model_validate(resolution.parameters)
    case = _case_or_404(db, resolution)
    from app.modules.cases.service import update_case

    update_case(
        db,
        case=case,
        actor_id=actor_id,
        changes={"priority": params.priority},
        summary=f"Priority set to {params.priority.value} by resolution",
    )
    return {"case_id": str(case.id), "priority": params.priority.value}


def execute_assign_case(db: Session, resolution: Resolution, actor_id: uuid.UUID | None) -> dict[str, Any]:
    params = AssignParams.model_validate(resolution.parameters)
    case = _case_or_404(db, resolution)
    from app.modules.cases.service import assign_case

    assign_case(db, case=case, user_id=params.user_id, actor_id=actor_id, reason=params.reason)
    return {"case_id": str(case.id), "assigned_user_id": str(params.user_id)}


def execute_retry_integration(
    db: Session, resolution: Resolution, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    params = RetryIntegrationParams.model_validate(resolution.parameters)
    from app.modules.integrations.service import test_connection

    result = test_connection(db, org_id=resolution.org_id, integration_id=params.integration_id)
    case = _case_or_404(db, resolution)
    _activity(db, case, actor_id, "Integration connection retried", {"result": result})
    if not result.get("ok"):
        raise UnprocessableError(
            f"Integration retry failed: {result.get('detail', 'unknown error')}",
            code="integration_retry_failed",
        )
    return result


def execute_retry_job(db: Session, resolution: Resolution, actor_id: uuid.UUID | None) -> dict[str, Any]:
    params = RetryJobParams.model_validate(resolution.parameters)
    from app.models.automation import BackgroundJob
    from app.workers.dispatch import retry_job

    job = db.get(BackgroundJob, params.job_id)
    if job is None or job.org_id != resolution.org_id:
        raise NotFoundError("Background job not found.", code="job_not_found")
    retry_job(job.id, job.org_id)
    case = _case_or_404(db, resolution)
    _activity(db, case, actor_id, f"Background job {job.task_name} retried", {"job_id": str(job.id)})
    return {"job_id": str(job.id), "task": job.task_name, "status": "queued"}


def execute_create_email_draft(
    db: Session, resolution: Resolution, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    params = EmailDraftParams.model_validate(resolution.parameters)
    case = _case_or_404(db, resolution)
    # A draft is intentionally not sent: it is stored for a human to review and send manually.
    draft = {"to": params.to, "subject": params.subject, "body": params.body, "sent": False}
    if case.assigned_user_id:
        notify(
            db,
            org_id=resolution.org_id,
            user_id=case.assigned_user_id,
            type=NotificationType.CASE_CREATED,
            title=f"Email draft ready for {case.case_number}",
            body=f"To {params.to}: {params.subject}",
            entity_type="CASE",
            entity_id=case.id,
        )
    _activity(db, case, actor_id, "Email draft created (not sent)", {"to": params.to})
    return {"draft": draft}


def execute_notify_team(db: Session, resolution: Resolution, actor_id: uuid.UUID | None) -> dict[str, Any]:
    params = NotifyTeamParams.model_validate(resolution.parameters)
    case = _case_or_404(db, resolution)
    recipients = user_ids_with_permission(db, org_id=resolution.org_id, permission="case:read")
    for user_id in recipients:
        notify(
            db,
            org_id=resolution.org_id,
            user_id=user_id,
            type=NotificationType.CASE_ESCALATED,
            title=f"Team notice for {case.case_number}",
            body=params.message,
            entity_type="CASE",
            entity_id=case.id,
        )
    _activity(db, case, actor_id, "Team notified", {"recipients": len(recipients)})
    return {"notified": len(recipients)}


def execute_mark_duplicate(
    db: Session, resolution: Resolution, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    params = MarkDuplicateParams.model_validate(resolution.parameters)
    if params.invoice_id == params.duplicate_invoice_id:
        raise BadRequestError("An invoice cannot be a duplicate of itself.", code="invalid_duplicate")
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.id == params.invoice_id,
            Invoice.org_id == resolution.org_id,
            Invoice.deleted_at.is_(None),
        )
    )
    original = db.scalar(
        select(Invoice).where(
            Invoice.id == params.duplicate_invoice_id,
            Invoice.org_id == resolution.org_id,
            Invoice.deleted_at.is_(None),
        )
    )
    if invoice is None or original is None:
        raise NotFoundError("Invoice not found.", code="invoice_not_found")
    if invoice.status in {InvoiceStatus.APPROVED, InvoiceStatus.READY_FOR_EXPORT}:
        raise UnprocessableError(
            "An approved invoice cannot be marked as a duplicate.", code="invoice_already_approved"
        )
    invoice.status = InvoiceStatus.REJECTED
    invoice.notes = ((invoice.notes or "") + f"\nMarked duplicate of {original.invoice_number}. {params.note}").strip()
    for record in db.scalars(
        select(ExceptionRecord).where(
            ExceptionRecord.org_id == resolution.org_id,
            ExceptionRecord.entity_type == "INVOICE",
            ExceptionRecord.entity_id == invoice.id,
            ExceptionRecord.status.in_([ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.LINKED]),
        )
    ).all():
        record.status = ExceptionStatus.RESOLVED
        record.resolved_at = utcnow()
        record.resolved_by_id = actor_id
        record.resolution_note = f"Duplicate of {original.invoice_number}"
    case = _case_or_404(db, resolution)
    _activity(
        db,
        case,
        actor_id,
        f"Invoice {invoice.invoice_number} marked as duplicate of {original.invoice_number}",
        {"duplicate_of": str(original.id)},
    )
    return {"invoice_id": str(invoice.id), "duplicate_of": str(original.id)}


def execute_escalate_case(db: Session, resolution: Resolution, actor_id: uuid.UUID | None) -> dict[str, Any]:
    params = EscalateParams.model_validate(resolution.parameters)
    case = _case_or_404(db, resolution)
    from app.modules.cases.service import escalate_case

    escalate_case(db, case=case, actor_id=actor_id, reason=params.reason, priority=params.priority)
    return {"case_id": str(case.id), "priority": params.priority.value}


def execute_create_approval_request(
    db: Session, resolution: Resolution, actor_id: uuid.UUID | None
) -> dict[str, Any]:
    case = _case_or_404(db, resolution)
    from app.modules.cases.service import transition

    if case.status in {CaseStatus.OPEN, CaseStatus.INVESTIGATING}:
        transition(
            db,
            case=case,
            new_status=CaseStatus.AWAITING_APPROVAL,
            actor_id=actor_id,
            note="Approval workflow opened",
        )
    _activity(db, case, actor_id, "Case moved to awaiting approval", {})
    return {"case_id": str(case.id), "status": case.status.value}


ACTION_REGISTRY: dict[ActionType, ActionDefinition] = {
    ActionType.REQUEST_VENDOR_CONFIRMATION: ActionDefinition(
        action_type=ActionType.REQUEST_VENDOR_CONFIRMATION,
        label="Request vendor confirmation",
        description="Send an email asking the vendor to confirm invoice details.",
        parameters_model=VendorConfirmationParams,
        required_permissions=("resolution:execute",),
        default_risk=RiskLevel.MEDIUM,
        external_side_effect=True,
        financial_impact=False,
        executor=execute_vendor_confirmation,
        policy_notes="External communication always requires approval.",
    ),
    ActionType.REQUEST_MISSING_DOCUMENTS: ActionDefinition(
        action_type=ActionType.REQUEST_MISSING_DOCUMENTS,
        label="Request missing documents",
        description="Ask the vendor for the documents required to resolve the case.",
        parameters_model=MissingDocumentsParams,
        required_permissions=("resolution:execute",),
        default_risk=RiskLevel.MEDIUM,
        external_side_effect=True,
        financial_impact=False,
        executor=execute_request_missing_documents,
        policy_notes="External communication always requires approval.",
    ),
    ActionType.UPDATE_CASE_PRIORITY: ActionDefinition(
        action_type=ActionType.UPDATE_CASE_PRIORITY,
        label="Update case priority",
        description="Change the operational priority of the case.",
        parameters_model=PriorityParams,
        required_permissions=("resolution:execute", "case:update"),
        default_risk=RiskLevel.LOW,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_update_priority,
    ),
    ActionType.ASSIGN_CASE: ActionDefinition(
        action_type=ActionType.ASSIGN_CASE,
        label="Assign case",
        description="Assign the case to a specific investigator.",
        parameters_model=AssignParams,
        required_permissions=("resolution:execute", "case:assign"),
        default_risk=RiskLevel.LOW,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_assign_case,
    ),
    ActionType.RETRY_INTEGRATION: ActionDefinition(
        action_type=ActionType.RETRY_INTEGRATION,
        label="Retry integration",
        description="Re-test the external integration connection.",
        parameters_model=RetryIntegrationParams,
        required_permissions=("resolution:execute", "workflow:run"),
        default_risk=RiskLevel.LOW,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_retry_integration,
    ),
    ActionType.RETRY_BACKGROUND_JOB: ActionDefinition(
        action_type=ActionType.RETRY_BACKGROUND_JOB,
        label="Retry background job",
        description="Requeue a failed background job.",
        parameters_model=RetryJobParams,
        required_permissions=("resolution:execute", "workflow:run"),
        default_risk=RiskLevel.LOW,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_retry_job,
    ),
    ActionType.CREATE_EMAIL_DRAFT: ActionDefinition(
        action_type=ActionType.CREATE_EMAIL_DRAFT,
        label="Create email draft",
        description="Prepare an email for a human to review; nothing is sent.",
        parameters_model=EmailDraftParams,
        required_permissions=("resolution:execute",),
        default_risk=RiskLevel.LOW,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_create_email_draft,
    ),
    ActionType.NOTIFY_TEAM: ActionDefinition(
        action_type=ActionType.NOTIFY_TEAM,
        label="Notify team",
        description="Send an in-app notice to everyone who can read cases.",
        parameters_model=NotifyTeamParams,
        required_permissions=("resolution:execute",),
        default_risk=RiskLevel.LOW,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_notify_team,
    ),
    ActionType.MARK_DUPLICATE: ActionDefinition(
        action_type=ActionType.MARK_DUPLICATE,
        label="Mark invoice as duplicate",
        description="Reject an invoice as a duplicate of another invoice and resolve its exceptions.",
        parameters_model=MarkDuplicateParams,
        required_permissions=("resolution:execute", "case:close"),
        default_risk=RiskLevel.HIGH,
        external_side_effect=False,
        financial_impact=True,
        executor=execute_mark_duplicate,
        policy_notes="High-risk financial action; approval is mandatory.",
    ),
    ActionType.ESCALATE_CASE: ActionDefinition(
        action_type=ActionType.ESCALATE_CASE,
        label="Escalate case",
        description="Raise the priority and notify the operations managers.",
        parameters_model=EscalateParams,
        required_permissions=("resolution:execute", "case:assign"),
        default_risk=RiskLevel.MEDIUM,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_escalate_case,
    ),
    ActionType.CREATE_APPROVAL_REQUEST: ActionDefinition(
        action_type=ActionType.CREATE_APPROVAL_REQUEST,
        label="Open approval workflow",
        description="Move the case into the awaiting-approval state.",
        parameters_model=NoParams,
        required_permissions=("resolution:execute", "case:update"),
        default_risk=RiskLevel.LOW,
        external_side_effect=False,
        financial_impact=False,
        executor=execute_create_approval_request,
    ),
}


def action_catalog() -> list[dict[str, Any]]:
    return [
        {
            "action_type": definition.action_type.value,
            "label": definition.label,
            "description": definition.description,
            "required_permissions": list(definition.required_permissions),
            "default_risk": definition.default_risk.value,
            "external_side_effect": definition.external_side_effect,
            "financial_impact": definition.financial_impact,
            "policy_notes": definition.policy_notes,
            "parameters_schema": definition.parameters_model.model_json_schema(),
        }
        for definition in ACTION_REGISTRY.values()
    ]


def get_definition(action_type: ActionType | str) -> ActionDefinition:
    try:
        key = ActionType(action_type)
    except ValueError as exc:
        raise BadRequestError(f"Unknown action type '{action_type}'.", code="unknown_action") from exc
    definition = ACTION_REGISTRY.get(key)
    if definition is None:
        raise BadRequestError(f"Action '{key.value}' is not enabled.", code="action_not_enabled")
    return definition


def validate_parameters(action_type: ActionType | str, parameters: dict[str, Any]) -> BaseModel:
    definition = get_definition(action_type)
    try:
        return definition.parameters_model.model_validate(parameters or {})
    except Exception as exc:  # pydantic ValidationError
        raise BadRequestError(
            "Action parameters are invalid.",
            code="invalid_action_parameters",
            details=str(exc)[:500],
        ) from exc


__all__ = [
    "ACTION_REGISTRY",
    "ActionDefinition",
    "action_catalog",
    "get_definition",
    "validate_parameters",
]
