"""Deterministic, versioned exception detection rules.

Rules only produce findings. Persistence, deduplication and case grouping are handled by
the detection service, which also records the rule code and version on every exception.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.money import money, percent_difference, tax_from_subtotal, within_tolerance
from app.core.text import name_similarity, similarity
from app.domain.enums import (
    DocumentStatus,
    DocumentType,
    ExceptionType,
    ExtractionRunStatus,
    JobStatus,
    ReviewStatus,
    Severity,
    VendorStatus,
    WebhookStatus,
    WorkflowStatus,
)
from app.models.automation import BackgroundJob, WebhookEvent, WorkflowExecution
from app.models.cases import ExceptionRule, ExceptionRuleVersion
from app.models.documents import Document, DocumentExtraction, ExtractedField
from app.models.finance import Invoice, InvoiceItem, PurchaseOrder, Vendor


@dataclass(slots=True)
class Finding:
    exception_type: ExceptionType
    severity: Severity
    title: str
    description: str
    evidence: dict[str, Any]
    dedupe_key: str
    entity_type: str = "INVOICE"
    entity_id: uuid.UUID | None = None


@dataclass(slots=True)
class RuleContext:
    db: Session
    org_id: uuid.UUID
    invoice: Invoice | None = None
    vendor: Vendor | None = None
    purchase_order: PurchaseOrder | None = None
    org_settings: dict[str, Any] = field(default_factory=dict)
    config: dict[str, Any] = field(default_factory=dict)
    now: datetime = field(default_factory=lambda: datetime.now(UTC))

    def as_float(self, key: str, default: float) -> float:
        try:
            return float(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def as_decimal(self, key: str, default: str) -> Decimal:
        try:
            return Decimal(str(self.config.get(key, default)))
        except (ArithmeticError, ValueError):
            return Decimal(default)

    def as_int(self, key: str, default: int) -> int:
        try:
            return int(self.config.get(key, default))
        except (TypeError, ValueError):
            return default

    def as_bool(self, key: str, default: bool) -> bool:
        value = self.config.get(key, default)
        return bool(value)

    def as_list(self, key: str, default: list[Any]) -> list[Any]:
        value = self.config.get(key, default)
        return value if isinstance(value, list) else default


@dataclass(frozen=True, slots=True)
class RuleDefinition:
    code: str
    name: str
    description: str
    exception_type: ExceptionType
    severity: Severity
    applies_to: tuple[str, ...]
    default_config: dict[str, Any]
    conditions: dict[str, Any]
    test_cases: tuple[dict[str, Any], ...]
    evaluate: Any


def stable_key(*parts: object) -> str:
    return hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- Rule 1


def evaluate_duplicate_invoice(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None:
        return []
    window_days = ctx.as_int("date_window_days", 3)
    threshold = ctx.as_float("fuzzy_number_similarity", 0.9)
    compare_amount = ctx.as_bool("compare_amount", True)
    validate_currency = ctx.as_bool("require_same_currency", True)

    rows = ctx.db.scalars(
        select(Invoice).where(
            Invoice.org_id == ctx.org_id,
            Invoice.id != invoice.id,
            Invoice.deleted_at.is_(None),
            Invoice.normalized_invoice_number == invoice.normalized_invoice_number,
        )
    ).all()

    matches: list[dict[str, Any]] = []
    severity = Severity.MEDIUM
    reasons_seen: list[str] = []
    for other in rows:
        if validate_currency and other.currency != invoice.currency:
            continue
        reasons: list[str] = []
        if other.vendor_id == invoice.vendor_id:
            reasons.append("same vendor")
        elif other.vendor_id and invoice.vendor_id:
            reasons.append("different vendor")
        if other.normalized_invoice_number == invoice.normalized_invoice_number:
            reasons.append("same normalized invoice number")
        if compare_amount and other.total != invoice.total:
            reasons.append("different amount")
        elif compare_amount:
            reasons.append("same amount")
        exact_number = other.normalized_invoice_number == invoice.normalized_invoice_number
        same_amount = other.total == invoice.total
        same_vendor = other.vendor_id == invoice.vendor_id
        if exact_number and same_vendor and same_amount:
            severity = Severity.HIGH
            reasons_seen.extend(reasons)
            matches.append(
                {
                    "invoice_id": str(other.id),
                    "invoice_number": other.invoice_number,
                    "invoice_date": other.invoice_date.isoformat(),
                    "total": str(other.total),
                    "currency": other.currency,
                    "status": other.status.value,
                    "document_id": str(other.document_id) if other.document_id else None,
                    "match_type": "exact",
                    "reasons": reasons,
                }
            )
            continue
        if exact_number and same_vendor and not same_amount:
            reasons_seen.extend(reasons)
            matches.append(
                {
                    "invoice_id": str(other.id),
                    "invoice_number": other.invoice_number,
                    "invoice_date": other.invoice_date.isoformat(),
                    "total": str(other.total),
                    "currency": other.currency,
                    "status": other.status.value,
                    "document_id": str(other.document_id) if other.document_id else None,
                    "match_type": "same_number_different_amount",
                    "reasons": reasons,
                }
            )
            continue
        number_similarity = similarity(
            other.normalized_invoice_number, invoice.normalized_invoice_number
        )
        date_distance = abs((other.invoice_date - invoice.invoice_date).days)
        if (
            same_vendor
            and same_amount
            and date_distance <= window_days
            and number_similarity >= threshold
        ):
            severity = Severity.MEDIUM if severity != Severity.HIGH else severity
            reasons_seen.extend(reasons)
            matches.append(
                {
                    "invoice_id": str(other.id),
                    "invoice_number": other.invoice_number,
                    "invoice_date": other.invoice_date.isoformat(),
                    "total": str(other.total),
                    "currency": other.currency,
                    "status": other.status.value,
                    "document_id": str(other.document_id) if other.document_id else None,
                    "match_type": "fuzzy",
                    "number_similarity": round(number_similarity, 3),
                    "reasons": reasons,
                }
            )

    for other in ctx.db.scalars(
        select(Invoice).where(
            Invoice.org_id == ctx.org_id,
            Invoice.id != invoice.id,
            Invoice.deleted_at.is_(None),
            Invoice.document_id == invoice.document_id,
            Invoice.document_id.is_not(None),
        )
    ).all():
        if other.document_id == invoice.document_id:
            severity = Severity.HIGH
            matches.append(
                {
                    "invoice_id": str(other.id),
                    "invoice_number": other.invoice_number,
                    "match_type": "same_document",
                    "total": str(other.total),
                    "currency": other.currency,
                }
            )

    if not matches:
        return []
    return [
        Finding(
            exception_type=ExceptionType.DUPLICATE_INVOICE,
            severity=severity,
            title=f"Possible duplicate invoice {invoice.invoice_number}",
            description=(
                f"{len(matches)} other invoice(s) share the same normalized number"
                + (" and amount" if "same amount" in reasons_seen else "")
                + ". Deterministic comparison; a human must confirm before rejecting."
            ),
            evidence={
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "total": str(invoice.total),
                "currency": invoice.currency,
                "matches": matches,
                "thresholds": {"date_window_days": window_days, "fuzzy_number_similarity": threshold},
            },
            dedupe_key=stable_key("duplicate_invoice", invoice.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 2


def evaluate_amount_mismatch(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None or ctx.purchase_order is None:
        return []
    po = ctx.purchase_order
    absolute = ctx.as_decimal("absolute_tolerance", "1.00")
    percent = ctx.as_decimal("percentage_tolerance", "1.00")
    allow_partial = ctx.as_bool("allow_partial_invoices", True)
    tax_inclusive = ctx.as_bool("compare_tax_inclusive", True)

    invoice_amount = invoice.total if tax_inclusive else invoice.subtotal
    po_amount = po.total if tax_inclusive else po.subtotal
    if within_tolerance(invoice_amount, po_amount, absolute=absolute, percent=percent):
        return []

    delta_percent = percent_difference(invoice_amount, po_amount)
    if allow_partial and invoice.total <= po.total and delta_percent <= Decimal("25"):
        # A partial invoice is still flagged, but at lower severity, because the remaining
        # balance can be legitimately invoiced later.
        severity = Severity.MEDIUM
        partial = True
    else:
        severity = Severity.HIGH if delta_percent > Decimal("10") else Severity.MEDIUM
        partial = False

    return [
        Finding(
            exception_type=ExceptionType.AMOUNT_MISMATCH,
            severity=severity,
            title=f"Invoice total differs from PO {po.po_number}",
            description=(
                f"Invoice {invoice.invoice_number} totals {invoice.currency} {invoice.total}, "
                f"purchase order totals {po.currency} {po.total} "
                f"({delta_percent.quantize(Decimal('0.01'))}% difference). "
                "Tolerance: "
                f"{absolute} absolute or {percent}%."
            ),
            evidence={
                "invoice_total": str(invoice.total),
                "po_total": str(po.total),
                "difference": str(money(invoice_amount - po_amount)),
                "percent_difference": str(delta_percent.quantize(Decimal("0.01"))),
                "currency": invoice.currency,
                "tolerances": {"absolute": str(absolute), "percent": str(percent)},
                "partial_invoice": partial,
                "tax_inclusive_comparison": tax_inclusive,
            },
            dedupe_key=stable_key("amount_mismatch", invoice.id, po.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 3


def evaluate_vendor_mismatch(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None:
        return []
    vendor = ctx.vendor
    po = ctx.purchase_order
    reasons: list[str] = []
    evidence: dict[str, Any] = {}

    if po is not None:
        po_vendor = ctx.db.get(Vendor, po.vendor_id)
        if po_vendor is None:
            reasons.append("Purchase order vendor is missing")
        elif invoice.vendor_id and po_vendor.id != invoice.vendor_id:
            reasons.append("Invoice vendor differs from the purchase order vendor")
            evidence["po_vendor"] = {
                "id": str(po_vendor.id),
                "legal_name": po_vendor.legal_name,
                "tax_id": po_vendor.tax_id,
            }
        elif vendor is not None:
            if vendor.tax_id and po_vendor.tax_id and vendor.tax_id != po_vendor.tax_id:
                reasons.append("Vendor tax IDs differ between invoice and purchase order")
            if name_similarity(vendor.legal_name, po_vendor.legal_name) < 0.7:
                reasons.append("Vendor legal names differ materially")

    if vendor is not None and invoice.vendor_name_raw:
        score = name_similarity(vendor.legal_name, invoice.vendor_name_raw)
        if score < 0.6:
            reasons.append("Extracted vendor name does not match the linked vendor record")
            evidence["extracted_vendor_name"] = invoice.vendor_name_raw
            evidence["matched_vendor_name"] = vendor.legal_name
            evidence["name_similarity"] = round(score, 3)

    if vendor is not None and vendor.status == VendorStatus.BLOCKED:
        reasons.append("Vendor is blocked in the vendor master")

    if not reasons:
        return []
    evidence["vendor_id"] = str(vendor.id) if vendor else None
    evidence["purchase_order_id"] = str(po.id) if po else None
    return [
        Finding(
            exception_type=ExceptionType.VENDOR_MISMATCH,
            severity=Severity.HIGH,
            title="Vendor identity mismatch",
            description="; ".join(reasons),
            evidence={**evidence, "reasons": reasons},
            dedupe_key=stable_key("vendor_mismatch", invoice.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 4


def evaluate_missing_purchase_order(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None or invoice.purchase_order_id is not None:
        return []
    if not ctx.org_settings.get("require_purchase_order", True):
        return []
    exempt = set(ctx.org_settings.get("po_exempt_vendor_ids", []) or [])
    if invoice.vendor_id and str(invoice.vendor_id) in exempt:
        return []
    threshold = ctx.as_decimal("high_value_threshold", "5000.00")
    severity = Severity.HIGH if invoice.total >= threshold else Severity.MEDIUM
    return [
        Finding(
            exception_type=ExceptionType.MISSING_PURCHASE_ORDER,
            severity=severity,
            title=f"Invoice {invoice.invoice_number} has no purchase order",
            description=(
                "The organization requires a purchase order for this invoice. "
                "No purchase order reference could be matched deterministically."
            ),
            evidence={
                "invoice_id": str(invoice.id),
                "invoice_number": invoice.invoice_number,
                "total": str(invoice.total),
                "currency": invoice.currency,
                "vendor_id": str(invoice.vendor_id) if invoice.vendor_id else None,
                "high_value_threshold": str(threshold),
            },
            dedupe_key=stable_key("missing_po", invoice.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 5


def evaluate_missing_documents(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None:
        return []
    requirements = ctx.as_list(
        "requirements",
        [
            {"document_type": "INVOICE", "condition": "always"},
            {"document_type": "CONTRACT", "condition": "amount_over", "threshold": "1000.00"},
        ],
    )
    missing: list[dict[str, Any]] = []
    for requirement in requirements:
        doc_type = str(requirement.get("document_type", "OTHER"))
        condition = str(requirement.get("condition", "always"))
        if condition == "amount_over":
            try:
                threshold = Decimal(str(requirement.get("threshold", "0")))
            except ArithmeticError:
                threshold = Decimal("0")
            if invoice.total < threshold:
                continue
        if doc_type == "INVOICE":
            if invoice.document_id is None:
                missing.append({"document_type": doc_type, "reason": "No invoice document attached"})
            else:
                document = ctx.db.get(Document, invoice.document_id)
                if document is not None and document.status in {DocumentStatus.FAILED, DocumentStatus.REQUIRES_REVIEW}:
                    missing.append(
                        {
                            "document_type": doc_type,
                            "reason": f"Invoice document processing status is {document.status.value}",
                            "document_id": str(document.id),
                        }
                    )
        elif doc_type == "CONTRACT":
            if invoice.vendor_id is None:
                missing.append({"document_type": doc_type, "reason": "No vendor linked"})
                continue
            contract = ctx.db.scalar(
                select(Document)
                .where(
                    Document.org_id == ctx.org_id,
                    Document.document_type == DocumentType.CONTRACT,
                    Document.deleted_at.is_(None),
                    Document.vendor_id == invoice.vendor_id,
                )
                .limit(1)
            )
            if contract is None:
                missing.append(
                    {
                        "document_type": doc_type,
                        "reason": "No contract document found for the vendor",
                        "vendor_id": str(invoice.vendor_id),
                    }
                )
        elif doc_type == "PURCHASE_ORDER":
            if invoice.purchase_order_id is None:
                missing.append({"document_type": doc_type, "reason": "No purchase order linked"})
    if not missing:
        return []
    return [
        Finding(
            exception_type=ExceptionType.MISSING_DOCUMENTS,
            severity=Severity.MEDIUM,
            title="Required documents are missing",
            description="; ".join(item["reason"] for item in missing),
            evidence={"invoice_id": str(invoice.id), "missing": missing, "requirements": requirements},
            dedupe_key=stable_key("missing_documents", invoice.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 6


def evaluate_tax_discrepancy(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None:
        return []
    reasons: list[str] = []
    evidence: dict[str, Any] = {
        "subtotal": str(invoice.subtotal),
        "tax": str(invoice.tax),
        "total": str(invoice.total),
    }
    if abs(invoice.subtotal + invoice.tax - invoice.total) > Decimal("0.01"):
        reasons.append("Subtotal plus tax does not equal the invoice total")

    allowed_rates = [Decimal(str(rate)) for rate in ctx.as_list("allowed_rates", ["0", "7", "10", "20"])]
    explicit_rate = ctx.config.get("default_rate")
    if explicit_rate is not None:
        allowed_rates = [Decimal(str(explicit_rate))]

    if invoice.subtotal > 0:
        implied_rate = (invoice.tax / invoice.subtotal * Decimal("100")).quantize(Decimal("0.01"))
        evidence["implied_tax_rate"] = str(implied_rate)
        if allowed_rates and not any(abs(implied_rate - rate) <= Decimal("0.1") for rate in allowed_rates):
            reasons.append(
                f"Implied tax rate {implied_rate}% is not in the allowed rates "
                f"{[str(rate) for rate in allowed_rates]}"
            )

    items = ctx.db.scalars(
        select(InvoiceItem).where(InvoiceItem.invoice_id == invoice.id)
    ).all()
    line_tax = Decimal("0")
    for item in items:
        line_tax += tax_from_subtotal(item.line_total, item.tax_rate)
    if items and abs(line_tax - invoice.tax) > Decimal("0.01"):
        reasons.append("Tax recalculated from line items differs from the stated tax")
        evidence["line_tax_total"] = str(money(line_tax))

    if not reasons:
        return []
    return [
        Finding(
            exception_type=ExceptionType.TAX_DISCREPANCY,
            severity=Severity.HIGH,
            title="Tax or VAT discrepancy",
            description="; ".join(reasons),
            evidence={**evidence, "allowed_rates": [str(rate) for rate in allowed_rates], "reasons": reasons},
            dedupe_key=stable_key("tax_discrepancy", invoice.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 7


def evaluate_invalid_date(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None:
        return []
    reasons: list[str] = []
    severity = Severity.MEDIUM
    today = ctx.now.date()
    max_age_days = ctx.as_int("max_age_days", 365)

    if invoice.invoice_date > today:
        reasons.append("Invoice date is in the future")
        severity = Severity.HIGH
    if (today - invoice.invoice_date).days > max_age_days:
        reasons.append(f"Invoice date is older than {max_age_days} days")
    if invoice.due_date and invoice.due_date < invoice.invoice_date:
        reasons.append("Due date precedes the invoice date")
        severity = Severity.HIGH
    if ctx.purchase_order and ctx.purchase_order.expiration_date and invoice.invoice_date > ctx.purchase_order.expiration_date:
        reasons.append("Invoice date is after the purchase order expiration date")

    if invoice.vendor_id:
        from app.models.documents import Document

        contract = ctx.db.scalar(
            select(Document)
            .where(
                Document.org_id == ctx.org_id,
                Document.document_type == DocumentType.CONTRACT,
                Document.deleted_at.is_(None),
                Document.vendor_id == invoice.vendor_id,
            )
            .limit(1)
        )
        if contract is not None:
            expires_on = (contract.metadata_ or {}).get("expires_on")
            if expires_on:
                try:
                    expiry = datetime.fromisoformat(str(expires_on)).date()
                except ValueError:
                    expiry = None
                if expiry and invoice.invoice_date > expiry:
                    reasons.append(f"Vendor contract expired on {expiry.isoformat()}")
                    severity = Severity.HIGH

    if not reasons:
        return []
    return [
        Finding(
            exception_type=ExceptionType.INVALID_INVOICE_DATE,
            severity=severity,
            title="Invalid or risky invoice date",
            description="; ".join(reasons),
            evidence={
                "invoice_date": invoice.invoice_date.isoformat(),
                "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
                "max_age_days": max_age_days,
                "reasons": reasons,
            },
            dedupe_key=stable_key("invalid_date", invoice.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 8

DUPLICATE_VENDOR_THRESHOLD = 0.95


def evaluate_duplicate_vendor(ctx: RuleContext) -> list[Finding]:
    if ctx.vendor is None:
        return []
    vendor = ctx.vendor
    threshold = ctx.as_float("name_similarity_threshold", DUPLICATE_VENDOR_THRESHOLD)
    others = ctx.db.scalars(
        select(Vendor).where(
            Vendor.org_id == ctx.org_id,
            Vendor.id != vendor.id,
            Vendor.deleted_at.is_(None),
        )
    ).all()
    matches: list[dict[str, Any]] = []
    for other in others:
        reasons: list[str] = []
        if vendor.tax_id and other.tax_id and vendor.tax_id == other.tax_id:
            reasons.append("Same tax ID")
        if vendor.normalized_name and vendor.normalized_name == other.normalized_name:
            reasons.append("Same normalized legal name")
        else:
            score = name_similarity(vendor.legal_name, other.legal_name)
            if score >= threshold:
                reasons.append(f"Name similarity {score:.2f}")
        if reasons:
            matches.append(
                {
                    "vendor_id": str(other.id),
                    "legal_name": other.legal_name,
                    "vendor_number": other.vendor_number,
                    "tax_id": other.tax_id,
                    "status": other.status.value,
                    "reasons": reasons,
                }
            )
    if not matches:
        return []
    return [
        Finding(
            exception_type=ExceptionType.DUPLICATE_VENDOR,
            severity=Severity.MEDIUM,
            title=f"Possible duplicate vendor: {vendor.legal_name}",
            description=f"{len(matches)} vendor record(s) may describe the same legal entity.",
            evidence={"vendor_id": str(vendor.id), "candidates": matches, "thresholds": {"name_similarity": threshold}},
            dedupe_key=stable_key("duplicate_vendor", vendor.id),
            entity_type="VENDOR",
            entity_id=vendor.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 9


def evaluate_extraction_anomaly(ctx: RuleContext) -> list[Finding]:
    invoice = ctx.invoice
    if invoice is None or invoice.document_id is None:
        return []
    document = ctx.db.get(Document, invoice.document_id)
    if document is None:
        return []
    reasons: list[str] = []
    severity = Severity.MEDIUM
    evidence: dict[str, Any] = {"document_id": str(document.id), "document_status": document.status.value}

    if document.status == DocumentStatus.FAILED:
        reasons.append("Document processing failed")
        severity = Severity.HIGH
    elif document.status == DocumentStatus.REQUIRES_REVIEW:
        reasons.append("Document processing requires human review")

    low_confidence = ctx.as_float("low_confidence_threshold", 0.6)
    if document.ocr_confidence is not None and document.ocr_confidence < low_confidence:
        reasons.append(f"OCR confidence {document.ocr_confidence:.2f} is below {low_confidence:.2f}")

    extraction = ctx.db.scalar(
        select(DocumentExtraction)
        .where(DocumentExtraction.document_id == document.id)
        .order_by(DocumentExtraction.created_at.desc())
        .limit(1)
    )
    if extraction is None:
        reasons.append("No extraction run exists for the invoice document")
    else:
        evidence["extraction_id"] = str(extraction.id)
        evidence["extraction_status"] = extraction.status.value
        if extraction.status in {ExtractionRunStatus.FAILED, ExtractionRunStatus.REQUIRES_REVIEW}:
            reasons.append(f"Extraction status is {extraction.status.value}")
        fields = ctx.db.scalars(
            select(ExtractedField).where(ExtractedField.extraction_id == extraction.id)
        ).all()
        values: dict[str, set[str]] = {}
        for item in fields:
            if item.value:
                values.setdefault(item.field_name, set()).add(item.value.strip().lower())
        conflicts = {name: sorted(vals) for name, vals in values.items() if len(vals) > 1}
        if conflicts:
            reasons.append("Conflicting extraction results for " + ", ".join(sorted(conflicts)))
            evidence["conflicts"] = conflicts
        required_fields = ctx.as_list("required_fields", ["invoice_number", "invoice_date", "total"])
        present = {item.field_name for item in fields if item.effective_value}
        missing = [name for name in required_fields if name not in present]
        if missing:
            reasons.append("Missing required extracted fields: " + ", ".join(missing))
            evidence["missing_fields"] = missing
        low_fields = [
            {
                "field": item.field_name,
                "confidence": round(item.confidence, 3),
                "method": item.method.value,
            }
            for item in fields
            if item.review_status == ReviewStatus.PENDING and item.confidence < low_confidence
        ]
        if low_fields:
            evidence["low_confidence_fields"] = low_fields

    if not reasons:
        return []
    return [
        Finding(
            exception_type=ExceptionType.EXTRACTION_ANOMALY,
            severity=severity,
            title="Document extraction anomaly",
            description="; ".join(reasons),
            evidence={**evidence, "reasons": reasons},
            dedupe_key=stable_key("extraction_anomaly", document.id),
            entity_id=invoice.id,
        )
    ]


# --------------------------------------------------------------------------- Rule 10


def evaluate_integration_failure(ctx: RuleContext) -> list[Finding]:
    since = ctx.now - timedelta(hours=ctx.as_int("window_hours", 24))
    repeat_threshold = ctx.as_int("repeat_failure_threshold", 2)
    findings: list[Finding] = []

    webhook_failures = ctx.db.execute(
        select(WebhookEvent.integration_id, func.count())
        .where(
            WebhookEvent.org_id == ctx.org_id,
            WebhookEvent.status == WebhookStatus.FAILED,
            WebhookEvent.created_at >= since,
        )
        .group_by(WebhookEvent.integration_id)
    ).all()
    for integration_id, count in webhook_failures:
        if count >= repeat_threshold:
            findings.append(
                Finding(
                    exception_type=ExceptionType.INTEGRATION_FAILURE,
                    severity=Severity.HIGH,
                    title="Repeated webhook delivery failures",
                    description=f"{count} webhook deliveries failed in the last {ctx.as_int('window_hours', 24)} hours.",
                    evidence={
                        "integration_id": str(integration_id) if integration_id else None,
                        "failure_count": int(count),
                        "window_hours": ctx.as_int("window_hours", 24),
                    },
                    dedupe_key=stable_key("integration_failure", "webhook", integration_id),
                    entity_type="INTEGRATION",
                    entity_id=integration_id,
                )
            )

    workflow_failures = ctx.db.execute(
        select(WorkflowExecution.integration_id, WorkflowExecution.workflow_key, func.count())
        .where(
            WorkflowExecution.org_id == ctx.org_id,
            WorkflowExecution.status == WorkflowStatus.FAILED,
            WorkflowExecution.created_at >= since,
        )
        .group_by(WorkflowExecution.integration_id, WorkflowExecution.workflow_key)
    ).all()
    for integration_id, workflow_key, count in workflow_failures:
        if count >= repeat_threshold:
            findings.append(
                Finding(
                    exception_type=ExceptionType.INTEGRATION_FAILURE,
                    severity=Severity.MEDIUM,
                    title=f"Workflow {workflow_key} is failing repeatedly",
                    description=f"{count} executions failed in the last {ctx.as_int('window_hours', 24)} hours.",
                    evidence={
                        "integration_id": str(integration_id) if integration_id else None,
                        "workflow_key": workflow_key,
                        "failure_count": int(count),
                    },
                    dedupe_key=stable_key("integration_failure", "workflow", workflow_key, integration_id),
                    entity_type="INTEGRATION",
                    entity_id=integration_id,
                )
            )

    job_failures = ctx.db.execute(
        select(BackgroundJob.task_name, func.count())
        .where(
            BackgroundJob.org_id == ctx.org_id,
            BackgroundJob.status == JobStatus.FAILED,
            BackgroundJob.created_at >= since,
        )
        .group_by(BackgroundJob.task_name)
    ).all()
    for task_name, count in job_failures:
        if count >= max(repeat_threshold, 3):
            findings.append(
                Finding(
                    exception_type=ExceptionType.INTEGRATION_FAILURE,
                    severity=Severity.MEDIUM,
                    title=f"Background task {task_name} is failing repeatedly",
                    description=f"{count} background jobs failed in the last {ctx.as_int('window_hours', 24)} hours.",
                    evidence={"task_name": task_name, "failure_count": int(count)},
                    dedupe_key=stable_key("integration_failure", "job", task_name),
                    entity_type="INTEGRATION",
                    entity_id=None,
                )
            )
    return findings


# ------------------------------------------------------------------------- Registry


RULE_LIBRARY: dict[str, RuleDefinition] = {
    "DUP_INVOICE_001": RuleDefinition(
        code="DUP_INVOICE_001",
        name="Duplicate invoice detection",
        description=(
            "Detects invoices that share a normalized invoice number, vendor and amount, a nearby "
            "date with a highly similar number, or the same source document."
        ),
        exception_type=ExceptionType.DUPLICATE_INVOICE,
        severity=Severity.HIGH,
        applies_to=("INVOICE",),
        default_config={
            "date_window_days": 3,
            "fuzzy_number_similarity": 0.9,
            "compare_amount": True,
            "require_same_currency": True,
        },
        conditions={"entity": "INVOICE", "requires": ["invoice_number", "vendor_id", "total"]},
        test_cases=(
            {
                "name": "exact duplicate",
                "invoice_number": "INV-100",
                "existing": {"invoice_number": "INV-100", "total": "1200.00"},
                "expect": "DUPLICATE_INVOICE",
            },
            {
                "name": "different amount is not an exact duplicate",
                "invoice_number": "INV-101",
                "existing": {"invoice_number": "INV-101", "total": "999.00"},
                "expect": "NO_EXACT_MATCH",
            },
        ),
        evaluate=evaluate_duplicate_invoice,
    ),
    "AMOUNT_MISMATCH_001": RuleDefinition(
        code="AMOUNT_MISMATCH_001",
        name="Invoice amount mismatch",
        description="Compares invoice totals to the matched purchase order using absolute and percentage tolerances.",
        exception_type=ExceptionType.AMOUNT_MISMATCH,
        severity=Severity.HIGH,
        applies_to=("INVOICE",),
        default_config={
            "absolute_tolerance": "1.00",
            "percentage_tolerance": "1.00",
            "allow_partial_invoices": True,
            "compare_tax_inclusive": True,
        },
        conditions={"entity": "INVOICE", "requires": ["purchase_order_id", "total"]},
        test_cases=(
            {
                "name": "beyond tolerance",
                "invoice_total": "1100.00",
                "po_total": "1000.00",
                "tolerance": {"absolute": "1.00", "percent": "5.00"},
                "expect": "AMOUNT_MISMATCH",
            },
            {
                "name": "within tolerance",
                "invoice_total": "1004.00",
                "po_total": "1000.00",
                "tolerance": {"absolute": "1.00", "percent": "5.00"},
                "expect": "NO_MATCH",
            },
        ),
        evaluate=evaluate_amount_mismatch,
    ),
    "VENDOR_MISMATCH_001": RuleDefinition(
        code="VENDOR_MISMATCH_001",
        name="Vendor identity mismatch",
        description="Compares tax ID, linked vendor, PO vendor and extracted vendor name.",
        exception_type=ExceptionType.VENDOR_MISMATCH,
        severity=Severity.HIGH,
        applies_to=("INVOICE",),
        default_config={"name_similarity_threshold": 0.6},
        conditions={"entity": "INVOICE", "requires": ["vendor_id"]},
        test_cases=(
            {
                "name": "tax id differs",
                "invoice_vendor_tax_id": "TH123",
                "po_vendor_tax_id": "TH999",
                "expect": "VENDOR_MISMATCH",
            },
        ),
        evaluate=evaluate_vendor_mismatch,
    ),
    "MISSING_PO_001": RuleDefinition(
        code="MISSING_PO_001",
        name="Missing purchase order",
        description="Flags invoices without a purchase order when the organization policy requires one.",
        exception_type=ExceptionType.MISSING_PURCHASE_ORDER,
        severity=Severity.HIGH,
        applies_to=("INVOICE",),
        default_config={"high_value_threshold": "5000.00"},
        conditions={"entity": "INVOICE", "org_setting": "require_purchase_order"},
        test_cases=(
            {
                "name": "no purchase order",
                "purchase_order_id": None,
                "require_purchase_order": True,
                "expect": "MISSING_PURCHASE_ORDER",
            },
            {
                "name": "policy exemption",
                "purchase_order_id": None,
                "require_purchase_order": False,
                "expect": "NO_MATCH",
            },
        ),
        evaluate=evaluate_missing_purchase_order,
    ),
    "MISSING_DOCS_001": RuleDefinition(
        code="MISSING_DOCS_001",
        name="Missing required documents",
        description="Checks configurable document requirements such as invoice PDFs and vendor contracts.",
        exception_type=ExceptionType.MISSING_DOCUMENTS,
        severity=Severity.MEDIUM,
        applies_to=("INVOICE",),
        default_config={
            "requirements": [
                {"document_type": "INVOICE", "condition": "always"},
                {"document_type": "CONTRACT", "condition": "amount_over", "threshold": "1000.00"},
            ]
        },
        conditions={"entity": "INVOICE"},
        test_cases=(
            {
                "name": "contract required above threshold",
                "total": "5000.00",
                "documents": ["INVOICE"],
                "expect": "MISSING_DOCUMENTS",
            },
        ),
        evaluate=evaluate_missing_documents,
    ),
    "TAX_DISCREPANCY_001": RuleDefinition(
        code="TAX_DISCREPANCY_001",
        name="Tax / VAT discrepancy",
        description="Validates subtotal + tax = total and that the implied tax rate is an allowed rate.",
        exception_type=ExceptionType.TAX_DISCREPANCY,
        severity=Severity.HIGH,
        applies_to=("INVOICE",),
        default_config={"allowed_rates": ["0", "7", "10", "20"]},
        conditions={"entity": "INVOICE", "requires": ["subtotal", "tax", "total"]},
        test_cases=(
            {
                "name": "arithmetic mismatch",
                "subtotal": "100.00",
                "tax": "7.00",
                "total": "120.00",
                "expect": "TAX_DISCREPANCY",
            },
        ),
        evaluate=evaluate_tax_discrepancy,
    ),
    "INVALID_DATE_001": RuleDefinition(
        code="INVALID_DATE_001",
        name="Invalid invoice date",
        description="Detects future dates, implausible ages, due-before-invoice and expired contracts or POs.",
        exception_type=ExceptionType.INVALID_INVOICE_DATE,
        severity=Severity.MEDIUM,
        applies_to=("INVOICE",),
        default_config={"max_age_days": 365},
        conditions={"entity": "INVOICE", "requires": ["invoice_date"]},
        test_cases=(
            {"name": "future date", "invoice_date": "tomorrow", "expect": "INVALID_INVOICE_DATE"},
            {"name": "past date within policy", "invoice_date": "yesterday", "expect": "NO_MATCH"},
        ),
        evaluate=evaluate_invalid_date,
    ),
    "DUP_VENDOR_001": RuleDefinition(
        code="DUP_VENDOR_001",
        name="Duplicate vendor detection",
        description="Deterministic detection of vendor master duplicates by tax ID and normalized name.",
        exception_type=ExceptionType.DUPLICATE_VENDOR,
        severity=Severity.MEDIUM,
        applies_to=("VENDOR",),
        default_config={"name_similarity_threshold": 0.95},
        conditions={"entity": "VENDOR"},
        test_cases=(
            {
                "name": "same tax id",
                "vendor_a": {"tax_id": "TH0001"},
                "vendor_b": {"tax_id": "TH0001"},
                "expect": "DUPLICATE_VENDOR",
            },
        ),
        evaluate=evaluate_duplicate_vendor,
    ),
    "EXTRACTION_ANOMALY_001": RuleDefinition(
        code="EXTRACTION_ANOMALY_001",
        name="OCR / extraction anomaly",
        description="Detects failed processing, low OCR confidence, missing fields and conflicting extraction results.",
        exception_type=ExceptionType.EXTRACTION_ANOMALY,
        severity=Severity.HIGH,
        applies_to=("INVOICE",),
        default_config={
            "low_confidence_threshold": 0.6,
            "required_fields": ["invoice_number", "invoice_date", "total"],
        },
        conditions={"entity": "INVOICE", "requires": ["document_id"]},
        test_cases=(
            {
                "name": "missing total field",
                "fields": ["invoice_number", "invoice_date"],
                "expect": "EXTRACTION_ANOMALY",
            },
        ),
        evaluate=evaluate_extraction_anomaly,
    ),
    "INTEGRATION_FAILURE_001": RuleDefinition(
        code="INTEGRATION_FAILURE_001",
        name="Integration failure detection",
        description="Detects repeated webhook, workflow and background job failures.",
        exception_type=ExceptionType.INTEGRATION_FAILURE,
        severity=Severity.HIGH,
        applies_to=("INTEGRATION",),
        default_config={"window_hours": 24, "repeat_failure_threshold": 2},
        conditions={"entity": "ORGANIZATION"},
        test_cases=(
            {"name": "two webhook failures", "webhook_failures": 2, "expect": "INTEGRATION_FAILURE"},
        ),
        evaluate=evaluate_integration_failure,
    ),
}


def ensure_default_rules(
    db: Session, org_id: uuid.UUID, *, created_by_id: uuid.UUID | None = None
) -> None:
    """Create the default rule set and version 1 for a new organization (idempotent)."""
    existing = {
        rule.code
        for rule in db.scalars(select(ExceptionRule).where(ExceptionRule.org_id == org_id)).all()
    }
    for code, definition in RULE_LIBRARY.items():
        if code in existing:
            continue
        rule = ExceptionRule(
            org_id=org_id,
            code=code,
            name=definition.name,
            description=definition.description,
            exception_type=definition.exception_type,
            severity=definition.severity,
            applies_to=list(definition.applies_to),
            is_enabled=True,
            is_system=True,
            created_by_id=created_by_id,
            updated_by_id=created_by_id,
        )
        db.add(rule)
        db.flush()
        db.add(
            ExceptionRuleVersion(
                rule_id=rule.id,
                version=1,
                config=definition.default_config,
                conditions=definition.conditions,
                thresholds={"severity": definition.severity.value},
                test_cases=[dict(case) for case in definition.test_cases],
                is_active=True,
                change_note="Initial rule definition",
                created_by_id=created_by_id,
            )
        )
    db.flush()


def active_config(db: Session, rule: ExceptionRule) -> tuple[dict[str, Any], int]:
    version = db.scalar(
        select(ExceptionRuleVersion)
        .where(ExceptionRuleVersion.rule_id == rule.id, ExceptionRuleVersion.is_active.is_(True))
        .order_by(ExceptionRuleVersion.version.desc())
        .limit(1)
    )
    if version is None:
        definition = RULE_LIBRARY.get(rule.code)
        return (definition.default_config if definition else {}), 0
    return dict(version.config), version.version
