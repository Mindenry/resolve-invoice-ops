"""Invoice lifecycle, deterministic validation and purchase-order matching."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, NotFoundError
from app.core.logging import get_logger
from app.core.money import ZERO, money, tax_from_subtotal, within_tolerance
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.core.text import normalize_invoice_number
from app.domain.enums import (
    CaseStatus,
    DocumentType,
    EventType,
    ExceptionStatus,
    InvoiceStatus,
    PurchaseOrderStatus,
    ValidationStatus,
)
from app.models.cases import Case, ExceptionRecord
from app.models.documents import Document
from app.models.finance import Invoice, InvoiceItem, PurchaseOrder, Vendor
from app.modules.invoices.schemas import (
    InvoiceCreate,
    InvoiceDetail,
    InvoiceItemInput,
    InvoiceItemOut,
    InvoiceOut,
    InvoiceUpdate,
    ValidationCheck,
    VendorRef,
)
from app.modules.purchase_orders.service import candidates_for_invoice
from app.services.audit import record_audit
from app.services.events import emit_event

logger = get_logger(__name__)

ALLOWED_TRANSITIONS: dict[InvoiceStatus, set[InvoiceStatus]] = {
    InvoiceStatus.DRAFT: {InvoiceStatus.RECEIVED, InvoiceStatus.CANCELLED},
    InvoiceStatus.RECEIVED: {
        InvoiceStatus.PROCESSING,
        InvoiceStatus.VALIDATED,
        InvoiceStatus.REQUIRES_REVIEW,
        InvoiceStatus.REJECTED,
        InvoiceStatus.CANCELLED,
    },
    InvoiceStatus.PROCESSING: {
        InvoiceStatus.VALIDATED,
        InvoiceStatus.REQUIRES_REVIEW,
        InvoiceStatus.REJECTED,
        InvoiceStatus.CANCELLED,
    },
    InvoiceStatus.VALIDATED: {
        InvoiceStatus.MATCHED,
        InvoiceStatus.APPROVED,
        InvoiceStatus.REQUIRES_REVIEW,
        InvoiceStatus.REJECTED,
        InvoiceStatus.CANCELLED,
    },
    InvoiceStatus.MATCHED: {
        InvoiceStatus.APPROVED,
        InvoiceStatus.REQUIRES_REVIEW,
        InvoiceStatus.REJECTED,
        InvoiceStatus.CANCELLED,
    },
    InvoiceStatus.APPROVED: {InvoiceStatus.READY_FOR_EXPORT, InvoiceStatus.CANCELLED},
    InvoiceStatus.READY_FOR_EXPORT: {InvoiceStatus.CANCELLED},
    InvoiceStatus.REQUIRES_REVIEW: {
        InvoiceStatus.VALIDATED,
        InvoiceStatus.MATCHED,
        InvoiceStatus.REJECTED,
        InvoiceStatus.CANCELLED,
    },
    InvoiceStatus.REJECTED: set(),
    InvoiceStatus.CANCELLED: set(),
}

EDITABLE_STATUSES = {
    InvoiceStatus.DRAFT,
    InvoiceStatus.RECEIVED,
    InvoiceStatus.REQUIRES_REVIEW,
    InvoiceStatus.PROCESSING,
}

TOTAL_ABSOLUTE_TOLERANCE = Decimal("0.01")
MATCH_PERCENT_TOLERANCE = Decimal("2.0")


def get_invoice(db: Session, *, org_id: uuid.UUID, invoice_id: uuid.UUID) -> Invoice:
    invoice = db.scalar(
        select(Invoice).where(
            Invoice.id == invoice_id, Invoice.org_id == org_id, Invoice.deleted_at.is_(None)
        )
    )
    if invoice is None:
        raise NotFoundError("Invoice not found.", code="invoice_not_found")
    return invoice


def _vendor_or_none(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID | None) -> Vendor | None:
    if vendor_id is None:
        return None
    vendor = db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
    )
    if vendor is None:
        raise BadRequestError("Vendor not found in this organization.", code="vendor_not_found")
    return vendor


def _document_or_none(db: Session, org_id: uuid.UUID, document_id: uuid.UUID | None) -> Document | None:
    if document_id is None:
        return None
    document = db.scalar(
        select(Document).where(
            Document.id == document_id,
            Document.org_id == org_id,
            Document.deleted_at.is_(None),
        )
    )
    if document is None:
        raise BadRequestError("Document not found in this organization.", code="document_not_found")
    if document.document_type != DocumentType.INVOICE:
        raise BadRequestError(
            "Only invoice documents can be linked to an invoice.", code="invalid_document_type"
        )
    return document


def _po_or_none(db: Session, org_id: uuid.UUID, po_id: uuid.UUID | None) -> PurchaseOrder | None:
    if po_id is None:
        return None
    po = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id, PurchaseOrder.org_id == org_id, PurchaseOrder.deleted_at.is_(None)
        )
    )
    if po is None:
        raise BadRequestError("Purchase order not found in this organization.", code="purchase_order_not_found")
    return po


def _invoice_totals(
    items: list[InvoiceItemInput],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    subtotal = ZERO
    tax = ZERO
    for item in items:
        line = money(Decimal(item.quantity) * Decimal(item.unit_price))
        subtotal += line
        tax += tax_from_subtotal(line, Decimal(item.tax_rate))
    return money(subtotal), money(tax), money(subtotal + tax), money(tax)


def _replace_items(db: Session, invoice: Invoice, items: list[InvoiceItemInput]) -> None:
    for item in db.scalars(select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)).all():
        db.delete(item)
    db.flush()
    for index, item in enumerate(items, start=1):
        db.add(
            InvoiceItem(
                invoice_id=invoice.id,
                line_number=index,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                line_total=money(Decimal(item.quantity) * Decimal(item.unit_price)),
                purchase_order_item_id=item.purchase_order_item_id,
            )
        )
    db.flush()


def create_invoice(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    payload: InvoiceCreate,
    status: InvoiceStatus | None = None,
    is_demo: bool = False,
) -> Invoice:
    vendor = _vendor_or_none(db, org_id, payload.vendor_id)
    po = _po_or_none(db, org_id, payload.purchase_order_id)
    document = _document_or_none(db, org_id, payload.document_id)
    currency = (payload.currency or (vendor.currency if vendor else "USD")).upper()

    computed_subtotal, computed_tax, computed_total, _ = _invoice_totals(payload.items)
    subtotal = money(payload.subtotal) if payload.subtotal is not None else computed_subtotal
    tax = money(payload.tax) if payload.tax is not None else computed_tax
    total = money(payload.total) if payload.total is not None else money(subtotal + tax)

    invoice = Invoice(
        org_id=org_id,
        invoice_number=payload.invoice_number.strip(),
        normalized_invoice_number=normalize_invoice_number(payload.invoice_number),
        vendor_id=vendor.id if vendor else None,
        purchase_order_id=po.id if po else None,
        document_id=document.id if document else None,
        invoice_date=payload.invoice_date,
        due_date=payload.due_date or (payload.invoice_date + timedelta(days=payload.payment_terms_days)),
        currency=currency,
        subtotal=subtotal,
        tax=tax,
        total=total,
        payment_terms_days=payload.payment_terms_days,
        status=status or InvoiceStatus.RECEIVED,
        validation_status=ValidationStatus.PENDING,
        source=payload.source,
        vendor_name_raw=payload.vendor_name_raw or (vendor.legal_name if vendor else None),
        notes=payload.notes,
        is_demo=is_demo,
    )
    db.add(invoice)
    db.flush()
    if payload.items:
        _replace_items(db, invoice, payload.items)
    record_audit(
        db,
        org_id=org_id,
        action="invoice.created",
        entity_type="invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.invoice_number} created",
        actor_id=actor_id,
        after={
            "invoice_number": invoice.invoice_number,
            "total": str(invoice.total),
            "currency": invoice.currency,
            "vendor_id": str(invoice.vendor_id) if invoice.vendor_id else None,
        },
    )
    return invoice


def update_invoice(
    db: Session, *, invoice: Invoice, actor_id: uuid.UUID | None, payload: InvoiceUpdate
) -> Invoice:
    if invoice.status not in EDITABLE_STATUSES:
        raise BadRequestError(
            f"An invoice in status {invoice.status.value} can no longer be edited.",
            code="invoice_not_editable",
        )
    changes = payload.model_dump(exclude_unset=True, exclude={"items"})
    before: dict[str, Any] = {}
    for field, value in changes.items():
        if value is None:
            continue
        if field == "vendor_id":
            vendor = _vendor_or_none(db, invoice.org_id, value)
            value = vendor.id if vendor else None
        if field == "purchase_order_id":
            po = _po_or_none(db, invoice.org_id, value)
            value = po.id if po else None
        if field == "invoice_number":
            invoice.normalized_invoice_number = normalize_invoice_number(value)
        if field == "currency":
            value = str(value).upper()
        current = getattr(invoice, field)
        if current != value:
            before[field] = str(current) if current is not None else None
            setattr(invoice, field, value)
    if payload.items is not None:
        _replace_items(db, invoice, payload.items)
        recomputed_subtotal, recomputed_tax, recomputed_total, _ = _invoice_totals(payload.items)
        before["total"] = str(invoice.total)
        if "subtotal" not in changes:
            invoice.subtotal = recomputed_subtotal
        if "tax" not in changes:
            invoice.tax = recomputed_tax
        if "total" not in changes:
            invoice.total = recomputed_total
        before["recomputed_total"] = str(recomputed_total)
    invoice.validation_status = ValidationStatus.PENDING
    record_audit(
        db,
        org_id=invoice.org_id,
        action="invoice.updated",
        entity_type="invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.invoice_number} updated",
        actor_id=actor_id,
        before=before,
        after={"total": str(invoice.total), "currency": invoice.currency},
    )
    return invoice


def transition(
    db: Session,
    *,
    invoice: Invoice,
    status: InvoiceStatus,
    actor_id: uuid.UUID | None,
    note: str | None = None,
) -> Invoice:
    if status == invoice.status:
        return invoice
    if status not in ALLOWED_TRANSITIONS.get(invoice.status, set()):
        raise BadRequestError(
            f"Cannot change invoice status from {invoice.status.value} to {status.value}.",
            code="invalid_invoice_transition",
            details={"allowed": sorted(s.value for s in ALLOWED_TRANSITIONS.get(invoice.status, set()))},
        )
    if status == InvoiceStatus.APPROVED:
        if invoice.validation_status == ValidationStatus.FAILED:
            raise BadRequestError(
                "An invoice with failed validation cannot be approved.", code="invoice_validation_failed"
            )
    previous = invoice.status
    invoice.status = status
    if status == InvoiceStatus.APPROVED:
        invoice.approved_by_id = actor_id
        invoice.approved_at = utcnow()
    record_audit(
        db,
        org_id=invoice.org_id,
        action="invoice.status_changed",
        entity_type="invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.invoice_number}: {previous.value} -> {status.value}",
        actor_id=actor_id,
        before={"status": previous.value},
        after={"status": status.value, "note": note},
    )
    return invoice


def validate_invoice(db: Session, *, invoice: Invoice, actor_id: uuid.UUID | None) -> list[ValidationCheck]:
    """Deterministic validation. Every check is explainable and persisted as a note."""
    checks: list[ValidationCheck] = []
    items = list(
        db.scalars(
            select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.line_number)
        )
    )
    line_sum = money(sum((item.line_total for item in items), ZERO))
    expected_tax = money(
        sum((tax_from_subtotal(item.line_total, item.tax_rate) for item in items), ZERO)
    )

    def add(code: str, severity: str, message: str, **details: Any) -> None:
        checks.append(ValidationCheck(code=code, severity=severity, message=message, details=details))

    if invoice.subtotal < ZERO or invoice.tax < ZERO or invoice.total < ZERO:
        add("negative_amounts", "FAIL", "Invoice contains negative amounts.")

    if abs(invoice.subtotal + invoice.tax - invoice.total) > TOTAL_ABSOLUTE_TOLERANCE:
        add(
            "total_mismatch",
            "FAIL",
            "Subtotal plus tax does not equal the invoice total.",
            subtotal=str(invoice.subtotal),
            tax=str(invoice.tax),
            total=str(invoice.total),
            difference=str(money(invoice.subtotal + invoice.tax - invoice.total)),
        )

    if items:
        if abs(line_sum - invoice.subtotal) > TOTAL_ABSOLUTE_TOLERANCE:
            add(
                "line_sum_mismatch",
                "FAIL",
                "The sum of invoice line totals does not equal the subtotal.",
                line_sum=str(line_sum),
                subtotal=str(invoice.subtotal),
            )
        if abs(expected_tax - invoice.tax) > TOTAL_ABSOLUTE_TOLERANCE:
            add(
                "line_tax_mismatch",
                "WARN",
                "Tax recalculated from line tax rates differs from the stated tax.",
                expected_tax=str(expected_tax),
                stated_tax=str(invoice.tax),
            )

    today = utcnow().date()
    if invoice.invoice_date > today:
        add("future_invoice_date", "FAIL", "Invoice date is in the future.", invoice_date=invoice.invoice_date.isoformat())
    if invoice.invoice_date < date(2000, 1, 1):
        add("implausible_invoice_date", "WARN", "Invoice date is implausibly old.", invoice_date=invoice.invoice_date.isoformat())
    if invoice.due_date and invoice.due_date < invoice.invoice_date:
        add("due_before_invoice", "FAIL", "Due date precedes the invoice date.")
    if len(invoice.currency) != 3 or not invoice.currency.isalpha():
        add("invalid_currency", "FAIL", "Invoice currency is not a valid ISO code.", currency=invoice.currency)

    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    if vendor is None:
        add("missing_vendor", "FAIL", "Invoice is not linked to a vendor.")
    else:
        if vendor.status.value == "BLOCKED":
            add("vendor_blocked", "FAIL", "The vendor is blocked.", vendor_id=str(vendor.id))
        if vendor.status.value == "INACTIVE":
            add("vendor_inactive", "WARN", "The vendor is inactive.", vendor_id=str(vendor.id))
        if vendor.currency != invoice.currency:
            add(
                "vendor_currency_mismatch",
                "WARN",
                "Invoice currency differs from the vendor's default currency.",
                invoice_currency=invoice.currency,
                vendor_currency=vendor.currency,
            )

    po = db.get(PurchaseOrder, invoice.purchase_order_id) if invoice.purchase_order_id else None
    if po is not None:
        if po.currency != invoice.currency:
            add(
                "po_currency_mismatch",
                "FAIL",
                "Invoice currency differs from the purchase order currency.",
                invoice_currency=invoice.currency,
                po_currency=po.currency,
            )
        if invoice.vendor_id and po.vendor_id != invoice.vendor_id:
            add("po_vendor_mismatch", "FAIL", "Invoice vendor does not match the purchase order vendor.")
        if not within_tolerance(
            invoice.total,
            po.total,
            absolute=Decimal("1.00"),
            percent=MATCH_PERCENT_TOLERANCE,
        ):
            add(
                "po_total_mismatch",
                "WARN",
                "Invoice total differs from the purchase order total beyond tolerance.",
                invoice_total=str(invoice.total),
                po_total=str(po.total),
            )
        if po.expiration_date and invoice.invoice_date > po.expiration_date:
            add(
                "po_expired",
                "WARN",
                "Invoice date is after the purchase order expiration date.",
                po_expiration=po.expiration_date.isoformat(),
            )
    elif invoice.vendor_id:
        add("missing_purchase_order", "WARN", "Invoice is not linked to a purchase order.")

    duplicate = db.scalar(
        select(func.count())
        .select_from(Invoice)
        .where(
            Invoice.org_id == invoice.org_id,
            Invoice.id != invoice.id,
            Invoice.deleted_at.is_(None),
            Invoice.normalized_invoice_number == invoice.normalized_invoice_number,
            Invoice.vendor_id == invoice.vendor_id,
            Invoice.currency == invoice.currency,
        )
    )
    if duplicate:
        add(
            "possible_duplicate",
            "WARN",
            "Another invoice with the same number and vendor already exists.",
            duplicate_count=int(duplicate),
        )

    failed = sum(1 for check in checks if check.severity == "FAIL")
    warnings = sum(1 for check in checks if check.severity == "WARN")
    status = ValidationStatus.FAILED if failed else (ValidationStatus.WARNING if warnings else ValidationStatus.PASSED)
    invoice.validation_status = status
    invoice.validation_notes = [check.model_dump() for check in checks]
    if status == ValidationStatus.FAILED:
        if invoice.status not in {InvoiceStatus.DRAFT, InvoiceStatus.CANCELLED, InvoiceStatus.REJECTED}:
            invoice.status = InvoiceStatus.REQUIRES_REVIEW
    elif invoice.status in {InvoiceStatus.RECEIVED, InvoiceStatus.PROCESSING, InvoiceStatus.REQUIRES_REVIEW}:
        invoice.status = InvoiceStatus.VALIDATED
    record_audit(
        db,
        org_id=invoice.org_id,
        action="invoice.validated",
        entity_type="invoice",
        entity_id=invoice.id,
        summary=f"Invoice {invoice.invoice_number} validated: {status.value}",
        actor_id=actor_id,
        after={"validation_status": status.value, "failed": failed, "warnings": warnings},
    )
    emit_event(
        db,
        org_id=invoice.org_id,
        event_type=EventType.INVOICE_VALIDATED,
        entity_type="INVOICE",
        entity_id=invoice.id,
        payload={"status": status.value, "checks": len(checks), "failed": failed},
    )
    return checks


def match_purchase_order(
    db: Session,
    *,
    invoice: Invoice,
    actor_id: uuid.UUID | None,
    purchase_order_id: uuid.UUID | None = None,
    auto_match: bool = True,
) -> tuple[PurchaseOrder | None, list[dict[str, Any]]]:
    candidates = candidates_for_invoice(db, invoice=invoice)
    if purchase_order_id is not None:
        po = _po_or_none(db, invoice.org_id, purchase_order_id)
        assert po is not None
        if invoice.vendor_id and po.vendor_id != invoice.vendor_id:
            raise BadRequestError(
                "The purchase order belongs to a different vendor.", code="po_vendor_mismatch"
            )
        if po.currency != invoice.currency:
            raise BadRequestError(
                "The purchase order currency differs from the invoice currency.", code="po_currency_mismatch"
            )
        alignment = next((c for c in candidates if c["id"] == str(po.id)), None)
        invoice.purchase_order_id = po.id
        if alignment and alignment["within_tolerance"]:
            if invoice.status in {InvoiceStatus.VALIDATED, InvoiceStatus.REQUIRES_REVIEW}:
                invoice.status = InvoiceStatus.MATCHED
        record_audit(
            db,
            org_id=invoice.org_id,
            action="invoice.matched",
            entity_type="invoice",
            entity_id=invoice.id,
            summary=f"Invoice {invoice.invoice_number} matched to PO {po.po_number}",
            actor_id=actor_id,
            after={"purchase_order_id": str(po.id), "within_tolerance": bool(alignment and alignment["within_tolerance"])},
        )
        return po, candidates

    if not auto_match:
        return None, candidates
    exact = [candidate for candidate in candidates if candidate["within_tolerance"]]
    if len(exact) == 1:
        po_id = uuid.UUID(str(exact[0]["id"]))
        return match_purchase_order(
            db, invoice=invoice, actor_id=actor_id, purchase_order_id=po_id, auto_match=False
        )
    return None, candidates


def enrich_out(db: Session, invoice: Invoice) -> InvoiceOut:
    vendor = db.get(Vendor, invoice.vendor_id) if invoice.vendor_id else None
    po = db.get(PurchaseOrder, invoice.purchase_order_id) if invoice.purchase_order_id else None
    open_exceptions = db.scalar(
        select(func.count())
        .select_from(ExceptionRecord)
        .where(
            ExceptionRecord.org_id == invoice.org_id,
            ExceptionRecord.entity_type == "INVOICE",
            ExceptionRecord.entity_id == invoice.id,
            ExceptionRecord.status.in_(
                [ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.LINKED]
            ),
        )
    ) or 0
    case = db.scalar(
        select(Case)
        .join(ExceptionRecord, ExceptionRecord.case_id == Case.id)
        .where(
            ExceptionRecord.entity_type == "INVOICE",
            ExceptionRecord.entity_id == invoice.id,
            ExceptionRecord.case_id.is_not(None),
            Case.status.notin_([CaseStatus.CLOSED, CaseStatus.CANCELLED]),
        )
        .limit(1)
    )
    return InvoiceOut(
        id=invoice.id,
        invoice_number=invoice.invoice_number,
        vendor=VendorRef(
            id=vendor.id, legal_name=vendor.legal_name, vendor_number=vendor.vendor_number, tax_id=vendor.tax_id
        )
        if vendor
        else None,
        purchase_order_id=invoice.purchase_order_id,
        purchase_order_number=po.po_number if po else None,
        document_id=invoice.document_id,
        invoice_date=invoice.invoice_date,
        due_date=invoice.due_date,
        currency=invoice.currency,
        subtotal=invoice.subtotal,
        tax=invoice.tax,
        total=invoice.total,
        status=invoice.status,
        validation_status=invoice.validation_status,
        source=invoice.source,
        is_demo=invoice.is_demo,
        vendor_name_raw=invoice.vendor_name_raw,
        created_at=invoice.created_at,
        open_exception_count=int(open_exceptions),
        case_id=case.id if case else None,
    )


def detail(db: Session, invoice: Invoice) -> InvoiceDetail:
    base = enrich_out(db, invoice)
    items = db.scalars(
        select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id).order_by(InvoiceItem.line_number)
    ).all()
    exceptions = db.scalars(
        select(ExceptionRecord)
        .where(
            ExceptionRecord.org_id == invoice.org_id,
            ExceptionRecord.entity_type == "INVOICE",
            ExceptionRecord.entity_id == invoice.id,
        )
        .order_by(ExceptionRecord.last_detected_at.desc())
    ).all()
    approval = None
    case = db.scalar(
        select(Case)
        .join(ExceptionRecord, ExceptionRecord.case_id == Case.id)
        .where(
            ExceptionRecord.entity_type == "INVOICE",
            ExceptionRecord.entity_id == invoice.id,
            ExceptionRecord.case_id.is_not(None),
        )
        .limit(1)
    )
    if case is not None:
        approval = {"case_id": str(case.id), "case_number": case.case_number, "case_status": case.status.value}
    return InvoiceDetail(
        **base.model_dump(),
        payment_terms_days=invoice.payment_terms_days,
        notes=invoice.notes,
        validation_notes=invoice.validation_notes or [],
        items=[InvoiceItemOut.model_validate(item) for item in items],
        exceptions=[
            {
                "id": str(record.id),
                "exception_type": record.exception_type.value,
                "severity": record.severity.value,
                "status": record.status.value,
                "title": record.title,
                "case_id": str(record.case_id) if record.case_id else None,
            }
            for record in exceptions
        ],
        purchase_order_candidates=candidates_for_invoice(db, invoice=invoice),
        approval=approval,
    )


def list_invoices(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    search: str | None = None,
    status: list[InvoiceStatus] | None = None,
    validation_status: ValidationStatus | None = None,
    vendor_id: uuid.UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    has_exceptions: bool | None = None,
    exceptions_only: bool = False,
) -> tuple[list[InvoiceOut], int]:
    stmt = select(Invoice).where(Invoice.org_id == org_id, Invoice.deleted_at.is_(None))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Invoice.invoice_number).like(pattern),
                func.lower(Invoice.vendor_name_raw).like(pattern),
            )
        )
    if status:
        stmt = stmt.where(Invoice.status.in_(status))
    if validation_status:
        stmt = stmt.where(Invoice.validation_status == validation_status)
    if vendor_id:
        stmt = stmt.where(Invoice.vendor_id == vendor_id)
    if date_from:
        stmt = stmt.where(Invoice.invoice_date >= date_from)
    if date_to:
        stmt = stmt.where(Invoice.invoice_date <= date_to)
    if exceptions_only or has_exceptions:
        stmt = stmt.where(
            Invoice.id.in_(
                select(ExceptionRecord.entity_id).where(
                    ExceptionRecord.org_id == org_id,
                    ExceptionRecord.entity_type == "INVOICE",
                    ExceptionRecord.status.in_(
                        [ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.LINKED]
                    ),
                )
            )
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_column = {
        "invoice_date": Invoice.invoice_date,
        "total": Invoice.total,
        "created_at": Invoice.created_at,
        "due_date": Invoice.due_date,
        "status": Invoice.status,
    }.get(pagination.sort or "invoice_date", Invoice.invoice_date)
    ordering = sort_column.asc() if pagination.order == "asc" else sort_column.desc()
    rows = db.scalars(stmt.order_by(ordering, Invoice.id).offset(pagination.offset).limit(pagination.page_size)).all()
    return [enrich_out(db, invoice) for invoice in rows], total


def invoices_for_vendor(db: Session, *, org_id: uuid.UUID, vendor_id: uuid.UUID) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice)
            .where(Invoice.org_id == org_id, Invoice.vendor_id == vendor_id, Invoice.deleted_at.is_(None))
            .order_by(Invoice.invoice_date.desc())
        )
    )


def find_duplicate_invoices(db: Session, *, invoice: Invoice) -> list[Invoice]:
    return list(
        db.scalars(
            select(Invoice).where(
                Invoice.org_id == invoice.org_id,
                Invoice.id != invoice.id,
                Invoice.deleted_at.is_(None),
                Invoice.normalized_invoice_number == invoice.normalized_invoice_number,
                Invoice.vendor_id == invoice.vendor_id,
            )
        )
    )


def po_status_open(db: Session, po: PurchaseOrder) -> bool:
    return po.status in {
        PurchaseOrderStatus.OPEN,
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
        PurchaseOrderStatus.COMPLETED,
    }
