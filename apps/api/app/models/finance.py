"""Vendor, purchase order and invoice models."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.domain.enums import (
    InvoiceStatus,
    PurchaseOrderStatus,
    ValidationStatus,
    VendorStatus,
    enum_type,
)

MONEY = Numeric(18, 4)
QUANTITY = Numeric(16, 4)
RATE = Numeric(9, 4)


class Vendor(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OrgScopedMixin, Base):
    __tablename__ = "vendors"
    __table_args__ = (
        UniqueConstraint("org_id", "vendor_number", name="uq_vendor_org_number"),
        Index("ix_vendors_org_name", "org_id", "normalized_name"),
        Index("ix_vendors_org_tax", "org_id", "tax_id"),
    )

    vendor_number: Mapped[str] = mapped_column(String(40), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    tax_id: Mapped[str | None] = mapped_column(String(64), index=True)
    address_line1: Mapped[str | None] = mapped_column(String(200))
    address_line2: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(32))
    country: Mapped[str | None] = mapped_column(String(2))
    contact_name: Mapped[str | None] = mapped_column(String(160))
    email: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(64))
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    status: Mapped[VendorStatus] = mapped_column(
        enum_type(VendorStatus, "vendor_status"), default=VendorStatus.ACTIVE, nullable=False
    )
    risk_flags: Mapped[list[str]] = mapped_column(default=list, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class PurchaseOrder(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OrgScopedMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        UniqueConstraint("org_id", "po_number", name="uq_po_org_number"),
        Index("ix_po_org_status", "org_id", "status"),
    )

    po_number: Mapped[str] = mapped_column(String(60), nullable=False)
    vendor_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    expiration_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[PurchaseOrderStatus] = mapped_column(
        enum_type(PurchaseOrderStatus, "po_status"), default=PurchaseOrderStatus.DRAFT, nullable=False
    )
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    description: Mapped[str | None] = mapped_column(String(400))
    notes: Mapped[str | None] = mapped_column(Text)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)


class PurchaseOrderItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (UniqueConstraint("purchase_order_id", "line_number", name="uq_po_item_line"),)

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    received_quantity: Mapped[Decimal] = mapped_column(QUANTITY, default=Decimal("0"), nullable=False)


class Invoice(UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin, OrgScopedMixin, Base):
    """Invoices are intentionally not unique by (vendor, number).

    The duplicate-invoice rule must be able to persist and investigate a second invoice
    with the same number instead of rejecting it at the storage layer.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_org_number", "org_id", "normalized_invoice_number"),
        Index("ix_invoices_org_vendor", "org_id", "vendor_id"),
        Index("ix_invoices_org_status", "org_id", "status"),
        Index("ix_invoices_org_date", "org_id", "invoice_date"),
    )

    invoice_number: Mapped[str] = mapped_column(String(80), nullable=False)
    normalized_invoice_number: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vendors.id", ondelete="RESTRICT"), index=True
    )
    purchase_order_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_orders.id", ondelete="SET NULL"), index=True
    )
    document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("documents.id", ondelete="SET NULL"), index=True
    )
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("document_extractions.id", ondelete="SET NULL")
    )
    invoice_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    tax: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    total: Mapped[Decimal] = mapped_column(MONEY, default=Decimal("0"), nullable=False)
    payment_terms_days: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    status: Mapped[InvoiceStatus] = mapped_column(
        enum_type(InvoiceStatus, "invoice_status"), default=InvoiceStatus.DRAFT, nullable=False
    )
    validation_status: Mapped[ValidationStatus] = mapped_column(
        enum_type(ValidationStatus, "invoice_validation_status"),
        default=ValidationStatus.PENDING,
        nullable=False,
    )
    validation_notes: Mapped[list[dict[str, Any]]] = mapped_column(default=list, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="MANUAL", nullable=False)
    vendor_name_raw: Mapped[str | None] = mapped_column(String(200))
    buyer_name_raw: Mapped[str | None] = mapped_column(String(200))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    approved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)


class InvoiceItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "invoice_items"
    __table_args__ = (UniqueConstraint("invoice_id", "line_number", name="uq_invoice_item_line"),)

    invoice_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_number: Mapped[int] = mapped_column(Integer, nullable=False)
    description: Mapped[str] = mapped_column(String(400), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(RATE, default=Decimal("0"), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    purchase_order_item_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("purchase_order_items.id", ondelete="SET NULL")
    )
