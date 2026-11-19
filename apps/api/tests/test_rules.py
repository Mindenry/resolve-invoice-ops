"""Deterministic exception rule tests."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import func, select

from app.domain.enums import DocumentStatus, DocumentType, ExceptionType, Severity
from app.models.cases import ExceptionRecord
from app.models.documents import Document
from app.modules.exceptions import service as exception_service
from app.modules.exceptions.rules import RuleContext, evaluate_integration_failure
from tests.factories import make_invoice, make_po, make_vendor


def _types(records) -> set[str]:
    return {record.exception_type.value for record in records}


def test_duplicate_invoice_exact(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    original = make_invoice(db, org.org.id, vendor, number="INV-900", total="1070.00")
    duplicate = make_invoice(db, org.org.id, vendor, number="INV-900", total="1070.00")
    db.commit()

    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=duplicate, create_cases=False
    )
    assert "DUPLICATE_INVOICE" in _types(records)
    evidence = next(r for r in records if r.exception_type == ExceptionType.DUPLICATE_INVOICE).evidence
    assert any(match["invoice_id"] == str(original.id) for match in evidence["matches"])


def test_duplicate_invoice_same_number_different_amount_still_flagged(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    make_invoice(db, org.org.id, vendor, number="INV-901", total="500.00")
    second = make_invoice(db, org.org.id, vendor, number="INV-901", total="900.00")
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=second, create_cases=False
    )
    assert "DUPLICATE_INVOICE" in _types(records)
    duplicate = next(r for r in records if r.exception_type == ExceptionType.DUPLICATE_INVOICE)
    assert duplicate.severity in {Severity.MEDIUM, Severity.HIGH}


def test_duplicate_detection_is_idempotent(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    make_invoice(db, org.org.id, vendor, number="INV-902", total="100.00")
    invoice = make_invoice(db, org.org.id, vendor, number="INV-902", total="100.00")
    db.commit()
    exception_service.detect_for_invoice(db, org_id=org.org.id, invoice=invoice, create_cases=False)
    db.commit()
    exception_service.detect_for_invoice(db, org_id=org.org.id, invoice=invoice, create_cases=False)
    db.commit()
    count = db.scalar(
        select(func.count())
        .select_from(ExceptionRecord)
        .where(
            ExceptionRecord.org_id == org.org.id,
            ExceptionRecord.exception_type == ExceptionType.DUPLICATE_INVOICE,
        )
    )
    assert count == 1
    record = db.scalar(
        select(ExceptionRecord).where(ExceptionRecord.exception_type == ExceptionType.DUPLICATE_INVOICE)
    )
    assert record.detection_count == 2


def test_amount_mismatch_beyond_tolerance(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    po = make_po(db, org.org.id, vendor, unit_price="1000.00")
    invoice = make_invoice(db, org.org.id, vendor, po=po, subtotal="1100.00", total="1100.00")
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    assert "AMOUNT_MISMATCH" in _types(records)
    mismatch = next(r for r in records if r.exception_type == ExceptionType.AMOUNT_MISMATCH)
    from decimal import Decimal

    assert Decimal(str(mismatch.evidence["invoice_total"])) == Decimal("1100.00")
    assert Decimal(str(mismatch.evidence["po_total"])) == Decimal("1000.00")


def test_amount_within_tolerance_is_clean(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    po = make_po(db, org.org.id, vendor, unit_price="1000.00")
    invoice = make_invoice(db, org.org.id, vendor, po=po, subtotal="1000.50", total="1000.50")
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    assert "AMOUNT_MISMATCH" not in _types(records)


def test_missing_purchase_order_respects_policy(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    invoice = make_invoice(db, org.org.id, vendor, po=None, subtotal="7500.00", total="7500.00")
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    finding = next(r for r in records if r.exception_type == ExceptionType.MISSING_PURCHASE_ORDER)
    assert finding.severity == Severity.HIGH

    org.org.settings = {**org.org.settings, "require_purchase_order": False}
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    assert "MISSING_PURCHASE_ORDER" not in _types(records)


def test_tax_discrepancy_detected(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    invoice = make_invoice(
        db, org.org.id, vendor, subtotal="1000.00", tax="140.00", total="1140.00"
    )
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    finding = next(r for r in records if r.exception_type == ExceptionType.TAX_DISCREPANCY)
    assert finding.evidence["implied_tax_rate"] == "14.00"


def test_future_invoice_date_flagged(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    invoice = make_invoice(
        db, org.org.id, vendor, invoice_date=date.today() + timedelta(days=4), total="100.00"
    )
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    assert "INVALID_INVOICE_DATE" in _types(records)


def test_vendor_mismatch_between_invoice_and_po(db, org) -> None:
    vendor_a = make_vendor(db, org.org.id, number="V-A", name="Vendor Alpha Ltd.", tax_id="THA")
    vendor_b = make_vendor(db, org.org.id, number="V-B", name="Vendor Beta Ltd.", tax_id="THB")
    po = make_po(db, org.org.id, vendor_b, unit_price="800.00")
    invoice = make_invoice(db, org.org.id, vendor_a, po=po, subtotal="800.00", total="800.00")
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    finding = next(r for r in records if r.exception_type == ExceptionType.VENDOR_MISMATCH)
    assert "different" in finding.description.lower() or "differs" in finding.description.lower()


def test_duplicate_vendor_detection(db, org) -> None:
    vendor = make_vendor(db, org.org.id, number="V-1", name="Mekong Trading Co., Ltd.", tax_id="TH777")
    make_vendor(db, org.org.id, number="V-2", name="Mekong Trading Company Limited", tax_id="TH777")
    db.commit()
    records = exception_service.detect_for_vendor(db, org_id=org.org.id, vendor=vendor)
    assert "DUPLICATE_VENDOR" in _types(records)


def test_extraction_anomaly_for_failed_document(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    document = Document(
        org_id=org.org.id,
        original_filename="scanned.pdf",
        storage_filename="scanned.pdf",
        mime_type="application/pdf",
        size_bytes=100,
        sha256="a" * 64,
        storage_key="x/y.pdf",
        document_type=DocumentType.INVOICE,
        status=DocumentStatus.FAILED,
        processing_error="OCR engine unavailable",
        page_count=1,
    )
    db.add(document)
    db.flush()
    invoice = make_invoice(db, org.org.id, vendor, total="100.00")
    invoice.document_id = document.id
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    assert "EXTRACTION_ANOMALY" in _types(records)


def test_integration_failure_rule(db, org) -> None:
    from app.domain.enums import Direction, WebhookStatus
    from app.models.automation import WebhookEvent

    for index in range(2):
        db.add(
            WebhookEvent(
                org_id=org.org.id,
                direction=Direction.OUTBOUND,
                event_type="case.created",
                payload={},
                signature_valid=True,
                status=WebhookStatus.FAILED,
                idempotency_key=f"evt-{index}",
            )
        )
    db.commit()
    ctx = RuleContext(db=db, org_id=org.org.id, config={"window_hours": 24, "repeat_failure_threshold": 2})
    findings = evaluate_integration_failure(ctx)
    assert findings
    assert findings[0].exception_type == ExceptionType.INTEGRATION_FAILURE


def test_detection_creates_and_reuses_case(db, org) -> None:
    vendor = make_vendor(db, org.org.id)
    invoice = make_invoice(db, org.org.id, vendor, po=None, subtotal="6000.00", total="6000.00")
    db.commit()
    records = exception_service.detect_for_invoice(db, org_id=org.org.id, invoice=invoice)
    db.commit()
    assert records
    assert all(record.case_id is not None for record in records)
    case_ids = {record.case_id for record in records}
    assert len(case_ids) == 1

    detect_again = exception_service.detect_for_invoice(db, org_id=org.org.id, invoice=invoice)
    db.commit()
    assert {record.case_id for record in detect_again} == case_ids


def test_disabled_rule_is_not_evaluated(db, org, client) -> None:
    response = client.patch(
        "/api/v1/exceptions/rules/MISSING_PO_001",
        headers=org.headers[next(iter(org.headers))],
        json={"is_enabled": False},
    )
    assert response.status_code == 200
    vendor = make_vendor(db, org.org.id)
    invoice = make_invoice(db, org.org.id, vendor, po=None, subtotal="7000.00", total="7000.00")
    db.commit()
    records = exception_service.detect_for_invoice(
        db, org_id=org.org.id, invoice=invoice, create_cases=False
    )
    assert "MISSING_PURCHASE_ORDER" not in _types(records)


def test_rule_update_creates_new_version(db, org, client) -> None:
    headers = org.headers[next(iter(org.headers))]
    response = client.patch(
        "/api/v1/exceptions/rules/AMOUNT_MISMATCH_001",
        headers=headers,
        json={"config": {"absolute_tolerance": "5.00", "percentage_tolerance": "2.00"}},
    )
    assert response.status_code == 200
    detail = client.get("/api/v1/exceptions/rules/AMOUNT_MISMATCH_001", headers=headers).json()
    assert detail["active_version"] == 2
    assert len(detail["versions"]) == 2
    assert detail["config"]["absolute_tolerance"] == "5.00"
