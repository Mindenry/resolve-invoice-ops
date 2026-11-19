"""Test data factories built through the real service layer."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.domain.enums import DocumentType, InvoiceStatus, PurchaseOrderStatus, RiskLevel
from app.models.finance import Invoice, PurchaseOrder, Vendor
from app.modules.invoices.schemas import InvoiceCreate, InvoiceItemInput
from app.modules.invoices.service import create_invoice
from app.modules.purchase_orders.schemas import POItemInput, PurchaseOrderCreate
from app.modules.purchase_orders.service import create_purchase_order
from app.modules.vendors.schemas import VendorCreate
from app.modules.vendors.service import create_vendor


def make_vendor(
    db: Session, org_id: uuid.UUID, *, number: str = "V-001", name: str = "Acme Supplies Ltd.",
    tax_id: str | None = "TH0105550001", currency: str = "USD", email: str | None = "vendor@example.com",
    **kwargs,
) -> Vendor:
    vendor = create_vendor(
        db,
        org_id=org_id,
        actor_id=None,
        payload=VendorCreate(
            vendor_number=number,
            legal_name=name,
            tax_id=tax_id,
            currency=currency,
            email=email,
            **kwargs,
        ),
    )
    db.flush()
    return db.get(Vendor, vendor.id)


def make_po(
    db: Session,
    org_id: uuid.UUID,
    vendor: Vendor,
    *,
    number: str = "PO-1001",
    unit_price: str = "1000.00",
    quantity: str = "1",
    tax_rate: str = "0",
    status: PurchaseOrderStatus = PurchaseOrderStatus.OPEN,
    expiration_date: date | None = None,
) -> PurchaseOrder:
    po = create_purchase_order(
        db,
        org_id=org_id,
        actor_id=None,
        payload=PurchaseOrderCreate(
            po_number=number,
            vendor_id=vendor.id,
            currency=vendor.currency,
            issue_date=date.today() - timedelta(days=30),
            expiration_date=expiration_date or date.today() + timedelta(days=180),
            status=status,
            description="Test purchase order",
            items=[
                POItemInput(
                    description="Test item",
                    quantity=Decimal(quantity),
                    unit_price=Decimal(unit_price),
                    tax_rate=Decimal(tax_rate),
                )
            ],
        ),
    )
    db.flush()
    return db.get(PurchaseOrder, po.id)


def make_invoice(
    db: Session,
    org_id: uuid.UUID,
    vendor: Vendor | None,
    *,
    number: str = "INV-1001",
    po: PurchaseOrder | None = None,
    subtotal: str = "1000.00",
    tax: str = "0",
    total: str | None = None,
    invoice_date: date | None = None,
    due_date: date | None = None,
    currency: str = "USD",
    status: InvoiceStatus = InvoiceStatus.RECEIVED,
    items: bool = True,
) -> Invoice:
    total_value = Decimal(total) if total is not None else Decimal(subtotal) + Decimal(tax)
    invoice = create_invoice(
        db,
        org_id=org_id,
        actor_id=None,
        payload=InvoiceCreate(
            invoice_number=number,
            vendor_id=vendor.id if vendor else None,
            purchase_order_id=po.id if po else None,
            invoice_date=invoice_date or date.today(),
            due_date=due_date,
            currency=currency,
            subtotal=Decimal(subtotal),
            tax=Decimal(tax),
            total=total_value,
            payment_terms_days=30,
            source="MANUAL",
            vendor_name_raw=vendor.legal_name if vendor else None,
            items=[
                InvoiceItemInput(
                    description="Test service",
                    quantity=Decimal("1"),
                    unit_price=Decimal(subtotal),
                    tax_rate=Decimal("0"),
                )
            ]
            if items
            else [],
        ),
        status=status,
    )
    db.flush()
    return db.get(Invoice, invoice.id)


def make_contract(db: Session, org_id: uuid.UUID, vendor: Vendor, *, expires_on: str) -> uuid.UUID:
    from app.models.documents import Document

    document = Document(
        org_id=org_id,
        vendor_id=vendor.id,
        original_filename=f"contract-{vendor.vendor_number}.pdf",
        storage_filename=f"contract-{vendor.vendor_number}.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        sha256=uuid.uuid4().hex,
        storage_key=f"{org_id}/contracts/{vendor.vendor_number}.pdf",
        document_type=DocumentType.CONTRACT,
        status="INDEXED",
        metadata_={"expires_on": expires_on},
        page_count=1,
    )
    db.add(document)
    db.flush()
    return document.id


__all__ = ["RiskLevel", "make_contract", "make_invoice", "make_po", "make_vendor"]
