"""Vendor CRUD, deterministic duplicate detection and authorised merge."""

from __future__ import annotations

import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import ConflictError, NotFoundError, UnprocessableError
from app.core.jsonfilters import json_array_contains
from app.core.pagination import Pagination
from app.core.security import utcnow
from app.core.text import name_similarity, normalize_name, normalize_tax_id
from app.domain.enums import EventType, ExceptionStatus, VendorStatus
from app.models.cases import ExceptionRecord
from app.models.documents import Document
from app.models.finance import Invoice, PurchaseOrder, Vendor
from app.modules.vendors.schemas import (
    VendorCreate,
    VendorDetail,
    VendorDuplicateCandidate,
    VendorDuplicateGroup,
    VendorOut,
    VendorUpdate,
)
from app.services.audit import record_audit
from app.services.events import emit_event

DUPLICATE_SIMILARITY_THRESHOLD = 0.88


def get_vendor(db: Session, *, org_id: uuid.UUID, vendor_id: uuid.UUID) -> Vendor:
    vendor = db.scalar(
        select(Vendor).where(Vendor.id == vendor_id, Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
    )
    if vendor is None:
        raise NotFoundError("Vendor not found.", code="vendor_not_found")
    return vendor


def _invoice_count(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(Invoice)
        .where(Invoice.org_id == org_id, Invoice.vendor_id == vendor_id, Invoice.deleted_at.is_(None))
    ) or 0


def _open_exception_count(db: Session, org_id: uuid.UUID, vendor_id: uuid.UUID) -> int:
    return db.scalar(
        select(func.count())
        .select_from(ExceptionRecord)
        .where(
            ExceptionRecord.org_id == org_id,
            ExceptionRecord.entity_type == "VENDOR",
            ExceptionRecord.entity_id == vendor_id,
            ExceptionRecord.status.in_([ExceptionStatus.OPEN, ExceptionStatus.ACKNOWLEDGED, ExceptionStatus.LINKED]),
        )
    ) or 0


def _to_out(db: Session, org_id: uuid.UUID, vendor: Vendor) -> VendorOut:
    data = VendorOut.model_validate(vendor)
    data.invoice_count = _invoice_count(db, org_id, vendor.id)
    data.open_exception_count = _open_exception_count(db, org_id, vendor.id)
    return data


def _to_detail(db: Session, org_id: uuid.UUID, vendor: Vendor) -> VendorDetail:
    base = _to_out(db, org_id, vendor)
    pos = db.scalars(
        select(PurchaseOrder)
        .where(PurchaseOrder.org_id == org_id, PurchaseOrder.vendor_id == vendor.id, PurchaseOrder.deleted_at.is_(None))
        .order_by(PurchaseOrder.issue_date.desc())
        .limit(10)
    ).all()
    invoices = db.scalars(
        select(Invoice)
        .where(Invoice.org_id == org_id, Invoice.vendor_id == vendor.id, Invoice.deleted_at.is_(None))
        .order_by(Invoice.invoice_date.desc())
        .limit(10)
    ).all()
    documents = db.scalars(
        select(Document)
        .where(
            Document.org_id == org_id,
            Document.deleted_at.is_(None),
            Document.id.in_(
                select(Invoice.document_id).where(
                    Invoice.org_id == org_id, Invoice.vendor_id == vendor.id, Invoice.document_id.is_not(None)
                )
            ),
        )
        .order_by(Document.created_at.desc())
        .limit(10)
    ).all()
    exceptions = db.scalars(
        select(ExceptionRecord)
        .where(
            ExceptionRecord.org_id == org_id,
            ExceptionRecord.entity_type == "VENDOR",
            ExceptionRecord.entity_id == vendor.id,
        )
        .order_by(ExceptionRecord.last_detected_at.desc())
        .limit(10)
    ).all()
    return VendorDetail(
        **base.model_dump(),
        purchase_orders=[
            {
                "id": str(po.id),
                "po_number": po.po_number,
                "status": po.status.value,
                "total": str(po.total),
                "currency": po.currency,
                "issue_date": po.issue_date.isoformat(),
            }
            for po in pos
        ],
        recent_invoices=[
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
        documents=[
            {
                "id": str(document.id),
                "original_filename": document.original_filename,
                "document_type": document.document_type.value,
                "status": document.status.value,
            }
            for document in documents
        ],
        exceptions=[
            {
                "id": str(record.id),
                "exception_type": record.exception_type.value,
                "severity": record.severity.value,
                "status": record.status.value,
                "title": record.title,
            }
            for record in exceptions
        ],
    )


def list_vendors(
    db: Session,
    *,
    org_id: uuid.UUID,
    pagination: Pagination,
    search: str | None = None,
    status: VendorStatus | None = None,
    risk_flag: str | None = None,
) -> tuple[list[VendorOut], int]:
    stmt = select(Vendor).where(Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Vendor.legal_name).like(pattern),
                func.lower(Vendor.vendor_number).like(pattern),
                func.lower(Vendor.tax_id).like(pattern),
            )
        )
    if status:
        stmt = stmt.where(Vendor.status == status)
    if risk_flag:
        stmt = stmt.where(json_array_contains(db, Vendor.risk_flags, risk_flag))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    sort_column = {
        "legal_name": Vendor.legal_name,
        "created_at": Vendor.created_at,
        "status": Vendor.status,
        "vendor_number": Vendor.vendor_number,
    }.get(pagination.sort or "legal_name", Vendor.legal_name)
    ordering = sort_column.asc() if pagination.order == "asc" else sort_column.desc()
    rows = db.scalars(stmt.order_by(ordering).offset(pagination.offset).limit(pagination.page_size)).all()
    return [_to_out(db, org_id, vendor) for vendor in rows], total


def create_vendor(
    db: Session, *, org_id: uuid.UUID, actor_id: uuid.UUID | None, payload: VendorCreate
) -> VendorOut:
    vendor = Vendor(
        org_id=org_id,
        vendor_number=payload.vendor_number.strip(),
        legal_name=payload.legal_name.strip(),
        normalized_name=normalize_name(payload.legal_name),
        display_name=payload.display_name,
        tax_id=normalize_tax_id(payload.tax_id),
        address_line1=payload.address_line1,
        address_line2=payload.address_line2,
        city=payload.city,
        postal_code=payload.postal_code,
        country=payload.country.upper() if payload.country else None,
        contact_name=payload.contact_name,
        email=str(payload.email) if payload.email else None,
        phone=payload.phone,
        payment_terms_days=payload.payment_terms_days,
        currency=payload.currency.upper(),
        status=payload.status,
        risk_flags=payload.risk_flags,
        notes=payload.notes,
    )
    try:
        with db.begin_nested():
            db.add(vendor)
            db.flush()
    except IntegrityError as exc:
        raise ConflictError("A vendor with this vendor number already exists.", code="vendor_number_taken") from exc
    record_audit(
        db,
        org_id=org_id,
        action="vendor.created",
        entity_type="vendor",
        entity_id=vendor.id,
        summary=f"Vendor {vendor.legal_name} created",
        actor_id=actor_id,
        after={"legal_name": vendor.legal_name, "vendor_number": vendor.vendor_number},
    )
    return _to_out(db, org_id, vendor)


def update_vendor(
    db: Session, *, vendor: Vendor, actor_id: uuid.UUID | None, payload: VendorUpdate
) -> VendorOut:
    changes = payload.model_dump(exclude_unset=True)
    before: dict[str, object] = {}
    for field, value in changes.items():
        if field == "tax_id":
            value = normalize_tax_id(value)
        if field == "legal_name" and value:
            vendor.normalized_name = normalize_name(value)
        if field == "currency" and value:
            value = value.upper()
        if field == "country" and value:
            value = value.upper()
        current = getattr(vendor, field)
        if current != value:
            before[field] = str(current) if current is not None else None
            setattr(vendor, field, value)
    if before:
        record_audit(
            db,
            org_id=vendor.org_id,
            action="vendor.updated",
            entity_type="vendor",
            entity_id=vendor.id,
            summary=f"Vendor {vendor.legal_name} updated",
            actor_id=actor_id,
            before=before,
        )
    return _to_out(db, vendor.org_id, vendor)


def archive_vendor(db: Session, *, vendor: Vendor, actor_id: uuid.UUID | None) -> None:
    vendor.deleted_at = utcnow()
    vendor.status = VendorStatus.INACTIVE
    record_audit(
        db,
        org_id=vendor.org_id,
        action="vendor.archived",
        entity_type="vendor",
        entity_id=vendor.id,
        summary=f"Vendor {vendor.legal_name} archived",
        actor_id=actor_id,
    )


def detail(db: Session, *, org_id: uuid.UUID, vendor_id: uuid.UUID) -> VendorDetail:
    return _to_detail(db, org_id, get_vendor(db, org_id=org_id, vendor_id=vendor_id))


def find_duplicates(db: Session, *, org_id: uuid.UUID, limit: int = 100) -> list[VendorDuplicateGroup]:
    vendors = list(
        db.scalars(
            select(Vendor)
            .where(Vendor.org_id == org_id, Vendor.deleted_at.is_(None))
            .order_by(Vendor.legal_name)
            .limit(limit)
        )
    )
    groups: list[VendorDuplicateGroup] = []
    for anchor in vendors:
        candidates: list[VendorDuplicateCandidate] = []
        for other in vendors:
            if other.id == anchor.id:
                continue
            reasons: list[str] = []
            score = 0.0
            if anchor.tax_id and other.tax_id and anchor.tax_id == other.tax_id:
                reasons.append("Same tax ID")
                score = max(score, 1.0)
            if anchor.normalized_name and anchor.normalized_name == other.normalized_name:
                reasons.append("Same normalized legal name")
                score = max(score, 0.98)
            else:
                similarity = name_similarity(anchor.legal_name, other.legal_name)
                if similarity >= DUPLICATE_SIMILARITY_THRESHOLD:
                    reasons.append(f"Name similarity {similarity:.2f}")
                    score = max(score, similarity)
            if anchor.email and other.email and anchor.email.lower() == other.email.lower():
                reasons.append("Same contact email")
                score = max(score, 0.9)
            if reasons:
                candidates.append(
                    VendorDuplicateCandidate(
                        vendor_id=other.id,
                        legal_name=other.legal_name,
                        vendor_number=other.vendor_number,
                        tax_id=other.tax_id,
                        score=round(score, 3),
                        reasons=reasons,
                    )
                )
        if candidates:
            candidates.sort(key=lambda candidate: candidate.score, reverse=True)
            groups.append(VendorDuplicateGroup(anchor=_to_out(db, org_id, anchor), candidates=candidates))
    return groups


def merge_vendors(
    db: Session,
    *,
    org_id: uuid.UUID,
    target_id: uuid.UUID,
    source_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    note: str | None = None,
) -> VendorOut:
    if target_id == source_id:
        raise UnprocessableError("A vendor cannot be merged into itself.", code="invalid_merge")
    target = get_vendor(db, org_id=org_id, vendor_id=target_id)
    source = get_vendor(db, org_id=org_id, vendor_id=source_id)
    if source.status == VendorStatus.BLOCKED:
        raise UnprocessableError("Blocked vendors cannot be merged.", code="vendor_blocked")

    moved_invoices = 0
    for invoice in db.scalars(select(Invoice).where(Invoice.vendor_id == source.id)).all():
        invoice.vendor_id = target.id
        moved_invoices += 1
    moved_pos = 0
    for purchase_order in db.scalars(select(PurchaseOrder).where(PurchaseOrder.vendor_id == source.id)).all():
        purchase_order.vendor_id = target.id
        moved_pos += 1
    for record in db.scalars(
        select(ExceptionRecord).where(
            ExceptionRecord.entity_type == "VENDOR", ExceptionRecord.entity_id == source.id
        )
    ).all():
        record.entity_id = target.id

    source.status = VendorStatus.INACTIVE
    source.deleted_at = utcnow()
    source.risk_flags = [*source.risk_flags, f"merged_into:{target.id}"]
    record_audit(
        db,
        org_id=org_id,
        action="vendor.merged",
        entity_type="vendor",
        entity_id=target.id,
        summary=f"Vendor {source.legal_name} merged into {target.legal_name}",
        actor_id=actor_id,
        before={"source_id": str(source.id), "source_name": source.legal_name},
        after={"target_id": str(target.id), "invoices_moved": moved_invoices, "pos_moved": moved_pos},
        context={"note": note},
    )
    emit_event(
        db,
        org_id=org_id,
        event_type=EventType.VENDOR_MERGED,
        entity_type="VENDOR",
        entity_id=target.id,
        payload={"merge_source": str(source.id), "invoices_moved": moved_invoices},
    )
    return _to_out(db, org_id, target)
