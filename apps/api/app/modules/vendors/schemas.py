"""Vendor schemas."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import EmailStr, Field

from app.domain.enums import VendorStatus
from app.schemas.common import ORMModel


class VendorBase(ORMModel):
    legal_name: str = Field(min_length=1, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    contact_name: str | None = Field(default=None, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    payment_terms_days: int = Field(default=30, ge=0, le=365)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    status: VendorStatus = VendorStatus.ACTIVE
    risk_flags: list[str] = Field(default_factory=list, max_length=20)
    notes: str | None = Field(default=None, max_length=8000)


class VendorCreate(VendorBase):
    vendor_number: str = Field(min_length=1, max_length=40)
    display_name: str | None = Field(default=None, max_length=200)


class VendorUpdate(ORMModel):
    legal_name: str | None = Field(default=None, min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    tax_id: str | None = Field(default=None, max_length=64)
    address_line1: str | None = Field(default=None, max_length=200)
    address_line2: str | None = Field(default=None, max_length=200)
    city: str | None = Field(default=None, max_length=120)
    postal_code: str | None = Field(default=None, max_length=32)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    contact_name: str | None = Field(default=None, max_length=160)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=64)
    payment_terms_days: int | None = Field(default=None, ge=0, le=365)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    status: VendorStatus | None = None
    risk_flags: list[str] | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=8000)


class VendorOut(VendorBase):
    id: uuid.UUID
    vendor_number: str
    display_name: str | None = None
    normalized_name: str
    is_demo: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    invoice_count: int = 0
    open_exception_count: int = 0


class VendorDetail(VendorOut):
    purchase_orders: list[dict[str, Any]] = Field(default_factory=list)
    recent_invoices: list[dict[str, Any]] = Field(default_factory=list)
    documents: list[dict[str, Any]] = Field(default_factory=list)
    exceptions: list[dict[str, Any]] = Field(default_factory=list)


class VendorDuplicateCandidate(ORMModel):
    vendor_id: uuid.UUID
    legal_name: str
    vendor_number: str
    tax_id: str | None = None
    score: float
    reasons: list[str]


class VendorDuplicateGroup(ORMModel):
    anchor: VendorOut
    candidates: list[VendorDuplicateCandidate]


class VendorMergeRequest(ORMModel):
    source_vendor_id: uuid.UUID
    note: str | None = Field(default=None, max_length=1000)


class VendorSummary(ORMModel):
    id: uuid.UUID
    vendor_number: str
    legal_name: str
    tax_id: str | None = None
    currency: str
    status: VendorStatus


__all__ = ["Decimal"]
