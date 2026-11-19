"""Invoice schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.domain.enums import InvoiceStatus, ValidationStatus
from app.schemas.common import ORMModel


class InvoiceItemInput(ORMModel):
    description: str = Field(min_length=1, max_length=400)
    quantity: Decimal = Field(gt=0, max_digits=16, decimal_places=4)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=9, decimal_places=4)
    purchase_order_item_id: uuid.UUID | None = None


class InvoiceItemOut(ORMModel):
    id: uuid.UUID
    line_number: int
    description: str
    quantity: Decimal
    unit_price: Decimal
    tax_rate: Decimal
    line_total: Decimal
    purchase_order_item_id: uuid.UUID | None = None


class InvoiceCreate(ORMModel):
    invoice_number: str = Field(min_length=1, max_length=80)
    vendor_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    document_id: uuid.UUID | None = None
    invoice_date: date
    due_date: date | None = None
    currency: str = Field(default="USD", min_length=3, max_length=3)
    subtotal: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    total: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    items: list[InvoiceItemInput] = Field(default_factory=list, max_length=200)
    source: str = Field(default="MANUAL", max_length=30)
    vendor_name_raw: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=8000)


class InvoiceUpdate(ORMModel):
    invoice_number: str | None = Field(default=None, min_length=1, max_length=80)
    vendor_id: uuid.UUID | None = None
    purchase_order_id: uuid.UUID | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    subtotal: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    tax: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    total: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    items: list[InvoiceItemInput] | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=8000)


class VendorRef(ORMModel):
    id: uuid.UUID
    legal_name: str
    vendor_number: str
    tax_id: str | None = None


class InvoiceStatusChange(ORMModel):
    status: InvoiceStatus
    note: str | None = Field(default=None, max_length=1000)


class InvoiceMatchRequest(ORMModel):
    purchase_order_id: uuid.UUID | None = None
    auto_match: bool = True


class ValidationCheck(ORMModel):
    code: str
    severity: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class InvoiceValidationResult(ORMModel):
    invoice_id: uuid.UUID
    validation_status: ValidationStatus
    status: InvoiceStatus
    checks: list[ValidationCheck]
    failed_checks: int
    warning_checks: int


class InvoiceOut(ORMModel):
    id: uuid.UUID
    invoice_number: str
    vendor: VendorRef | None = None
    purchase_order_id: uuid.UUID | None = None
    purchase_order_number: str | None = None
    document_id: uuid.UUID | None = None
    invoice_date: date
    due_date: date | None = None
    currency: str
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    status: InvoiceStatus
    validation_status: ValidationStatus
    source: str
    is_demo: bool
    vendor_name_raw: str | None = None
    created_at: datetime | None = None
    open_exception_count: int = 0
    case_id: uuid.UUID | None = None


class InvoiceDetail(InvoiceOut):
    payment_terms_days: int
    notes: str | None = None
    validation_notes: list[dict[str, Any]] = Field(default_factory=list)
    items: list[InvoiceItemOut] = Field(default_factory=list)
    exceptions: list[dict[str, Any]] = Field(default_factory=list)
    purchase_order_candidates: list[dict[str, Any]] = Field(default_factory=list)
    approval: dict[str, Any] | None = None
