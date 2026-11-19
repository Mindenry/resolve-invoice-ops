"""Purchase order schemas."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from app.domain.enums import PurchaseOrderStatus
from app.schemas.common import ORMModel


class POItemInput(ORMModel):
    description: str = Field(min_length=1, max_length=400)
    quantity: Decimal = Field(gt=0, max_digits=16, decimal_places=4)
    unit_price: Decimal = Field(ge=0, max_digits=18, decimal_places=4)
    tax_rate: Decimal = Field(default=Decimal("0"), ge=0, le=100, max_digits=9, decimal_places=4)


class POItemOut(POItemInput):
    id: uuid.UUID
    line_number: int
    line_total: Decimal
    received_quantity: Decimal


class PurchaseOrderCreate(ORMModel):
    po_number: str = Field(min_length=1, max_length=60)
    vendor_id: uuid.UUID
    currency: str = Field(default="USD", min_length=3, max_length=3)
    issue_date: date
    expiration_date: date | None = None
    status: PurchaseOrderStatus = PurchaseOrderStatus.DRAFT
    description: str | None = Field(default=None, max_length=400)
    notes: str | None = Field(default=None, max_length=8000)
    items: list[POItemInput] = Field(min_length=1, max_length=200)


class PurchaseOrderUpdate(ORMModel):
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    issue_date: date | None = None
    expiration_date: date | None = None
    description: str | None = Field(default=None, max_length=400)
    notes: str | None = Field(default=None, max_length=8000)
    items: list[POItemInput] | None = Field(default=None, min_length=1, max_length=200)


class PurchaseOrderTransition(ORMModel):
    status: PurchaseOrderStatus
    note: str | None = Field(default=None, max_length=1000)


class PurchaseOrderOut(ORMModel):
    id: uuid.UUID
    po_number: str
    vendor_id: uuid.UUID
    vendor_name: str | None = None
    currency: str
    issue_date: date
    expiration_date: date | None = None
    status: PurchaseOrderStatus
    subtotal: Decimal
    tax: Decimal
    total: Decimal
    description: str | None = None
    is_demo: bool
    created_at: datetime | None = None
    invoiced_amount: Decimal = Decimal("0")
    invoice_count: int = 0


class PurchaseOrderDetail(PurchaseOrderOut):
    notes: str | None = None
    items: list[POItemOut] = Field(default_factory=list)
    invoices: list[dict[str, Any]] = Field(default_factory=list)
