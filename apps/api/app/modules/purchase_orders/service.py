"""Purchase order lifecycle, totals and invoice matching data."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BadRequestError, ConflictError, NotFoundError
from app.core.money import ZERO, money, tax_from_subtotal
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.domain.enums import InvoiceStatus, PurchaseOrderStatus
from app.models.finance import Invoice, PurchaseOrder, PurchaseOrderItem, Vendor
from app.modules.purchase_orders.schemas import (
    POItemInput,
    POItemOut,
    PurchaseOrderCreate,
    PurchaseOrderDetail,
    PurchaseOrderOut,
    PurchaseOrderUpdate,
)
from app.services.audit import record_audit

ALLOWED_TRANSITIONS: dict[PurchaseOrderStatus, set[PurchaseOrderStatus]] = {
    PurchaseOrderStatus.DRAFT: {PurchaseOrderStatus.OPEN, PurchaseOrderStatus.CANCELLED},
    PurchaseOrderStatus.OPEN: {
        PurchaseOrderStatus.PARTIALLY_RECEIVED,
        PurchaseOrderStatus.COMPLETED,
        PurchaseOrderStatus.CANCELLED,
        PurchaseOrderStatus.EXPIRED,
    },
    PurchaseOrderStatus.PARTIALLY_RECEIVED: {
        PurchaseOrderStatus.COMPLETED,
        PurchaseOrderStatus.CANCELLED,
        PurchaseOrderStatus.EXPIRED,
    },
    PurchaseOrderStatus.COMPLETED: set(),
    PurchaseOrderStatus.CANCELLED: set(),
    PurchaseOrderStatus.EXPIRED: {PurchaseOrderStatus.OPEN},
}

EDITABLE_STATUSES = {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.OPEN}


def get_purchase_order(db: Session, *, org_id: uuid.UUID, po_id: uuid.UUID) -> PurchaseOrder:
    po = db.scalar(
        select(PurchaseOrder).where(
            PurchaseOrder.id == po_id,
            PurchaseOrder.org_id == org_id,
            PurchaseOrder.deleted_at.is_(None),
        )
    )
    if po is None:
        raise NotFoundError("Purchase order not found.", code="purchase_order_not_found")
    return po


def get_vendor_or_404(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
    )
    if vendor is None:
        raise NotFoundError("Vendor not found.", code="vendor_not_found")
    return vendor


def compute_totals(items: list[POItemInput], currency: str) -> tuple[Decimal, Decimal, Decimal]:
    subtotal = ZERO
    tax = ZERO
    for item in items:
        line = money(Decimal(item.quantity) * Decimal(item.unit_price))
        subtotal += line
        tax += tax_from_subtotal(line, Decimal(item.tax_rate))
    subtotal = money(subtotal)
    tax = money(tax)
    return subtotal, tax, money(subtotal + tax)


def _replace_items(db: Session, po: PurchaseOrder, items: list[POItemInput]) -> None:
    for existing in db.scalars(
        select(PurchaseOrderItem).where(PurchaseOrderItem.purchase_order_id == po.id)
    ).all():
        db.delete(existing)
    db.flush()
    subtotal, tax, total = compute_totals(items, po.currency)
    for index, item in enumerate(items, start=1):
        line_total = money(Decimal(item.quantity) * Decimal(item.unit_price))
        db.add(
            PurchaseOrderItem(
                purchase_order_id=po.id,
                line_number=index,
                description=item.description,
                quantity=item.quantity,
                unit_price=item.unit_price,
                tax_rate=item.tax_rate,
                line_total=line_total,
            )
        )
    po.subtotal = subtotal
    po.tax = tax
    po.total = total
    db.flush()


def _invoiced(db: Session, po_id: uuid.UUID) -> tuple[Decimal, int]:
    rows = db.execute(
        select(func.coalesce(func.sum(Invoice.total), 0), func.count())
        .select_from(Invoice)
        .where(
            Invoice.purchase_order_id == po_id,
            Invoice.deleted_at.is_(None),
            Invoice.status.notin_([InvoiceStatus.CANCELLED, InvoiceStatus.REJECTED]),
        )
    ).one()
    return money(rows[0] or 0), int(rows[1] or 0)


def _to_out(db: Session, po: PurchaseOrder) -> PurchaseOrderOut:
    vendor = db.get(Vendor, po.vendor_id)
    invoiced, count = _invoiced(db, po.id)
    return PurchaseOrderOut(
        id=po.id,
        po_number=po.po_number,
        vendor_id=po.vendor_id,
        vendor_name=vendor.legal_name if vendor else None,
        currency=po.currency,
        issue_date=po.issue_date,
        expiration_date=po.expiration_date,
        status=po.status,
        subtotal=po.subtotal,
        tax=po.tax,
        total=po.total,
        description=po.description,
        is_demo=po.is_demo,
        created_at=po.created_at,
        invoiced_amount=invoiced,
        invoice_count=count,
    )


def detail(db: Session, po: PurchaseOrder) -> PurchaseOrderDetail:
    base = _to_out(db, po)
    items = db.scalars(
        select(PurchaseOrderItem)
        .where(PurchaseOrderItem.purchase_order_id == po.id)
        .order_by(PurchaseOrderItem.line_number)
    ).all()
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.purchase_order_id == po.id, Invoice.deleted_at.is_(None))
        .order_by(Invoice.invoice_date.desc())
    ).all()
    return PurchaseOrderDetail(
        **base.model_dump(),
        notes=po.notes,
        items=[POItemOut.model_validate(item) for item in items],
        invoices=[
            {
                "id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "status": invoice.status.value,
                "total": str(invoice.total),
                "currency": invoice.currency,
                "invoice_date": invoice.invoice_date.isoformat(),
            }
            for invoice in invoices
        ],
    )


def create_purchase_order(
    db: Session,
    *,
    org_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    payload: PurchaseOrderCreate,
) -> PurchaseOrder:
    vendor = get_vendor_or_404(db, org_id, payload.vendor_id)
    if payload.expiration_date and payload.expiration_date < payload.issue_date:
        raise BadRequestError("Expiration date cannot precede the issue date.", code="invalid_dates")
    currency = (payload.currency or vendor.currency).upper()
    po = PurchaseOrder(
        org_id=org_id,
        po_number=payload.po_number.strip(),
        vendor_id=vendor.id,
        currency=currency,
        issue_date=payload.issue_date,
        expiration_date=payload.expiration_date,
        status=payload.status if payload.status in {PurchaseOrderStatus.DRAFT, PurchaseOrderStatus.OPEN} else PurchaseOrderStatus.DRAFT,
        description=payload.description,
        notes=payload.notes,
        approved_by_id=actor_id if payload.status == PurchaseOrderStatus.OPEN else None,
    )
    try:
        with db.begin_nested():
            db.add(po)
            db.flush()
    except IntegrityError as exc:
        raise ConflictError("A purchase order with this number already exists.", code="po_number_taken") from exc
    _replace_items(db, po, payload.items)
    record_audit(
        db,
        org_id=org_id,
        action="purchase_order.created",
        entity_type="purchase_order",
        entity_id=po.id,
        summary=f"Purchase order {po.po_number} created",
        actor_id=actor_id,
        after={"po_number": po.po_number, "total": str(po.total), "currency": po.currency},
    )
    return po


def update_purchase_order(
    db: Session,
    *,
    po: PurchaseOrder,
    actor_id: uuid.UUID | None,
    payload: PurchaseOrderUpdate,
) -> PurchaseOrder:
    if po.status not in EDITABLE_STATUSES:
        raise BadRequestError(
            f"A purchase order in status {po.status.value} can no longer be edited.",
            code="purchase_order_not_editable",
        )
    before = {"total": str(po.total), "currency": po.currency}
    changes = payload.model_dump(exclude_unset=True, exclude={"items"})
    for field, value in changes.items():
        if value is not None:
            setattr(po, field, value.upper() if field == "currency" else value)
    if payload.items is not None:
        _replace_items(db, po, payload.items)
    record_audit(
        db,
        org_id=po.org_id,
        action="purchase_order.updated",
        entity_type="purchase_order",
        entity_id=po.id,
        summary=f"Purchase order {po.po_number} updated",
        actor_id=actor_id,
        before=before,
        after={"total": str(po.total), "currency": po.currency},
    )
    return po


def transition(db: Session, *, po: PurchaseOrder, status: PurchaseOrderStatus, actor_id: uuid.UUID | None, note: str | None = None) -> PurchaseOrder:
    if status == po.status:
        return po
    if status not in ALLOWED_TRANSITIONS.get(po.status, set()):
        raise BadRequestError(
            f"Cannot change purchase order status from {po.status.value} to {status.value}.",
            code="invalid_purchase_order_transition",
        )
    if status == PurchaseOrderStatus.OPEN and not po.approved_by_id:
        po.approved_by_id = actor_id
    previous = po.status
    po.status = status
    if status == PurchaseOrderStatus.OPEN and po.expiration_date and po.expiration_date < utcnow().date():
        raise BadRequestError("Cannot open an expired purchase order.", code="purchase_order_expired")
    record_audit(
        db,
        org_id=po.org_id,
        action="purchase_order.status_changed",
        entity_type="purchase_order",
        entity_id=po.id,
        summary=f"PO {po.po_number}: {previous.value} -> {status.value}",
        actor_id=actor_id,
        before={"status": previous.value},
        after={"status": status.value, "note": note},
    )
    return po


def refresh_expired(db: Session, *, org_id: uuid.UUID) -> int:
    today = utcnow().date()
    rows = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.org_id == org_id,
            PurchaseOrder.deleted_at.is_(None),
            PurchaseOrder.status.in_([PurchaseOrderStatus.OPEN, PurchaseOrderStatus.PARTIALLY_RECEIVED]),
            PurchaseOrder.expiration_date.is_not(None),
            PurchaseOrder.expiration_date < today,
        )
    ).all()
    for po in rows:
        po.status = PurchaseOrderStatus.EXPIRED
    return len(rows)


def list_purchase_orders(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    search: str | None = None,
    vendor_id: uuid.UUID | None = None,
    status: PurchaseOrderStatus | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> tuple[list[PurchaseOrderOut], int]:
    refresh_expired(db, org_id=org_id)
    stmt = select(PurchaseOrder).where(PurchaseOrder.org_id == org_id, PurchaseOrder.deleted_at.is_(None))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(PurchaseOrder.po_number).like(pattern),
                func.lower(PurchaseOrder.description).like(pattern),
            )
        )
    if vendor_id:
        stmt = stmt.where(PurchaseOrder.vendor_id == vendor_id)
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    if date_from:
        stmt = stmt.where(PurchaseOrder.issue_date >= date_from)
    if date_to:
        stmt = stmt.where(PurchaseOrder.issue_date <= date_to)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_column = {
        "issue_date": PurchaseOrder.issue_date,
        "total": PurchaseOrder.total,
        "po_number": PurchaseOrder.po_number,
        "created_at": PurchaseOrder.created_at,
    }.get(pagination.sort or "issue_date", PurchaseOrder.issue_date)
    ordering = sort_column.asc() if pagination.order == "asc" else sort_column.desc()
    rows = db.scalars(stmt.order_by(ordering).offset(pagination.offset).limit(pagination.page_size)).all()
    return [_to_out(db, po) for po in rows], total


def candidates_for_invoice(
    db: Session, *, invoice: Invoice, tolerance_percent: Decimal = Decimal("2")
) -> list[dict[str, object]]:
    """Deterministic candidate POs for an invoice (vendor + amount + date window)."""
    if invoice.vendor_id is None:
        return []
    rows = db.scalars(
        select(PurchaseOrder).where(
            PurchaseOrder.org_id == invoice.org_id,
            PurchaseOrder.vendor_id == invoice.vendor_id,
            PurchaseOrder.deleted_at.is_(None),
            PurchaseOrder.status.in_(
                [PurchaseOrderStatus.OPEN, PurchaseOrderStatus.PARTIALLY_RECEIVED, PurchaseOrderStatus.COMPLETED]
            ),
            PurchaseOrder.issue_date <= invoice.invoice_date,
        )
    ).all()
    results: list[dict[str, object]] = []
    for po in rows:
        difference = abs(po.total - invoice.total)
        percent = (difference / po.total * 100) if po.total else Decimal("0")
        results.append(
            {
                "id": str(po.id),
                "po_number": po.po_number,
                "total": str(po.total),
                "currency": po.currency,
                "percent_difference": f"{percent.quantize(Decimal('0.01'))}",
                "within_tolerance": bool(percent <= tolerance_percent and po.currency == invoice.currency),
            }
        )
    results.sort(key=lambda row: Decimal(str(row["percent_difference"])))
    return results
