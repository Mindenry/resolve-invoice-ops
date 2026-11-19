"""Invoice endpoints, validation and purchase order matching."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.pagination import Page, Pagination, pagination_params
from app.db.session import get_db
from app.dependencies.auth import Principal, require_permission
from app.domain.enums import InvoiceStatus, ValidationStatus
from app.modules.invoices import service
from app.modules.invoices.schemas import (
    InvoiceCreate,
    InvoiceDetail,
    InvoiceMatchRequest,
    InvoiceOut,
    InvoiceStatusChange,
    InvoiceUpdate,
    InvoiceValidationResult,
    ValidationCheck,
)
from app.schemas.common import APIMessage

router = APIRouter(prefix="/invoices", tags=["Invoices"])

InvoiceReader = Annotated[Principal, Depends(require_permission("invoice:read"))]
InvoiceCreator = Annotated[Principal, Depends(require_permission("invoice:create"))]
InvoiceEditor = Annotated[Principal, Depends(require_permission("invoice:update"))]
InvoiceApprover = Annotated[Principal, Depends(require_permission("invoice:approve"))]


@router.get("", response_model=Page[InvoiceOut], summary="List invoices")
def list_invoices(
    principal: InvoiceReader,
    db: Annotated[Session, Depends(get_db)],
    pagination: Annotated[Pagination, Depends(pagination_params)],
    search: str | None = Query(None, max_length=160),
    status: list[InvoiceStatus] | None = Query(None),
    validation_status: ValidationStatus | None = Query(None),
    vendor_id: uuid.UUID | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    exceptions_only: bool = Query(False),
) -> Page[InvoiceOut]:
    items, total = service.list_invoices(
        db,
        org_id=principal.org_id,
        pagination=pagination,
        search=search,
        status=status,
        validation_status=validation_status,
        vendor_id=vendor_id,
        date_from=date_from,
        date_to=date_to,
        exceptions_only=exceptions_only,
    )
    return Page.build(items, total, pagination)


@router.post("", response_model=InvoiceDetail, status_code=201, summary="Create an invoice")
def create_invoice(
    payload: InvoiceCreate, principal: InvoiceCreator, db: Annotated[Session, Depends(get_db)]
) -> InvoiceDetail:
    invoice = service.create_invoice(
        db, org_id=principal.org_id, actor_id=principal.user_id, payload=payload
    )
    if invoice.status in {InvoiceStatus.RECEIVED, InvoiceStatus.DRAFT}:
        service.validate_invoice(db, invoice=invoice, actor_id=principal.user_id)
        from app.modules.exceptions.service import detect_for_invoice

        detect_for_invoice(db, org_id=principal.org_id, invoice=invoice, actor_id=principal.user_id)
    db.commit()
    return service.detail(db, invoice)


@router.get("/{invoice_id}", response_model=InvoiceDetail, summary="Invoice detail")
def get_invoice(
    invoice_id: uuid.UUID, principal: InvoiceReader, db: Annotated[Session, Depends(get_db)]
) -> InvoiceDetail:
    invoice = service.get_invoice(db, org_id=principal.org_id, invoice_id=invoice_id)
    return service.detail(db, invoice)


@router.patch("/{invoice_id}", response_model=InvoiceDetail, summary="Update an invoice")
def update_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceUpdate,
    principal: InvoiceEditor,
    db: Annotated[Session, Depends(get_db)],
) -> InvoiceDetail:
    invoice = service.get_invoice(db, org_id=principal.org_id, invoice_id=invoice_id)
    service.update_invoice(db, invoice=invoice, actor_id=principal.user_id, payload=payload)
    db.commit()
    return service.detail(db, invoice)


@router.post("/{invoice_id}/validate", response_model=InvoiceValidationResult, summary="Validate an invoice")
def validate_invoice(
    invoice_id: uuid.UUID,
    principal: InvoiceEditor,
    db: Annotated[Session, Depends(get_db)],
    run_exception_detection: bool = Query(True),
) -> InvoiceValidationResult:
    invoice = service.get_invoice(db, org_id=principal.org_id, invoice_id=invoice_id)
    checks = service.validate_invoice(db, invoice=invoice, actor_id=principal.user_id)
    if run_exception_detection:
        from app.modules.exceptions.service import detect_for_invoice

        detect_for_invoice(db, org_id=principal.org_id, invoice=invoice, actor_id=principal.user_id)
    db.commit()
    return InvoiceValidationResult(
        invoice_id=invoice.id,
        validation_status=invoice.validation_status,
        status=invoice.status,
        checks=checks,
        failed_checks=sum(1 for check in checks if check.severity == "FAIL"),
        warning_checks=sum(1 for check in checks if check.severity == "WARN"),
    )


@router.post("/{invoice_id}/match", response_model=InvoiceDetail, summary="Match a purchase order")
def match_purchase_order(
    invoice_id: uuid.UUID,
    payload: InvoiceMatchRequest,
    principal: InvoiceEditor,
    db: Annotated[Session, Depends(get_db)],
) -> InvoiceDetail:
    invoice = service.get_invoice(db, org_id=principal.org_id, invoice_id=invoice_id)
    service.match_purchase_order(
        db,
        invoice=invoice,
        actor_id=principal.user_id,
        purchase_order_id=payload.purchase_order_id,
        auto_match=payload.auto_match,
    )
    db.commit()
    return service.detail(db, invoice)


@router.post("/{invoice_id}/transition", response_model=InvoiceDetail, summary="Change invoice status")
def transition_invoice(
    invoice_id: uuid.UUID,
    payload: InvoiceStatusChange,
    principal: InvoiceEditor,
    db: Annotated[Session, Depends(get_db)],
) -> InvoiceDetail:
    invoice = service.get_invoice(db, org_id=principal.org_id, invoice_id=invoice_id)
    if payload.status in {InvoiceStatus.APPROVED, InvoiceStatus.READY_FOR_EXPORT}:
        if "invoice:approve" not in principal.permissions:
            from app.core.errors import ForbiddenError

            raise ForbiddenError("You do not have permission to approve invoices.", code="missing_permission")
    service.transition(
        db, invoice=invoice, status=payload.status, actor_id=principal.user_id, note=payload.note
    )
    db.commit()
    return service.detail(db, invoice)


@router.post("/{invoice_id}/approve", response_model=InvoiceDetail, summary="Approve an invoice")
def approve_invoice(
    invoice_id: uuid.UUID, principal: InvoiceApprover, db: Annotated[Session, Depends(get_db)]
) -> InvoiceDetail:
    invoice = service.get_invoice(db, org_id=principal.org_id, invoice_id=invoice_id)
    service.transition(
        db, invoice=invoice, status=InvoiceStatus.APPROVED, actor_id=principal.user_id, note="Approved"
    )
    db.commit()
    return service.detail(db, invoice)


@router.delete("/{invoice_id}", response_model=APIMessage, summary="Cancel an invoice")
def cancel_invoice(
    invoice_id: uuid.UUID, principal: InvoiceEditor, db: Annotated[Session, Depends(get_db)]
) -> APIMessage:
    invoice = service.get_invoice(db, org_id=principal.org_id, invoice_id=invoice_id)
    if invoice.status in {InvoiceStatus.CANCELLED, InvoiceStatus.REJECTED}:
        return APIMessage(message="Invoice is already closed.")
    from app.core.security import utcnow
    from app.services.audit import record_audit

    invoice.status = InvoiceStatus.CANCELLED
    invoice.deleted_at = utcnow()
    record_audit(
        db,
        org_id=principal.org_id,
        action="invoice.cancelled",
        entity_type="invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.invoice_number} cancelled",
        actor=principal.user,
    )
    db.commit()
    return APIMessage(message="Invoice cancelled.")


# Explicit schema import keeps the validation response documented accurately.
_ = ValidationCheck
