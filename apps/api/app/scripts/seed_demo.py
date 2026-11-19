"""Seed a complete, obviously-labelled demo organization.

Run from apps/api:  python -m app.scripts.seed_demo
All data is synthetic. Documents are generated PDFs. No external service is called.
"""

from __future__ import annotations

import os

os.environ.setdefault("TASK_RUNNER", "inline")

import io
import json
import random
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.config.settings import REPO_ROOT, settings
from app.core.security import hash_password
from app.db.session import SessionLocal, init_models
from app.domain.enums import (
    CaseStatus,
    DocumentType,
    IntegrationKind,
    IntegrationStatus,
    InvoiceStatus,
    Priority,
    PurchaseOrderStatus,
    RiskLevel,
    Severity,
    VendorStatus,
    WorkflowStatus,
)
from app.models.automation import Integration, WorkflowExecution
from app.models.cases import Case, CaseActivity, CaseComment, ExceptionRecord
from app.models.documents import Document
from app.models.evaluation import EvaluationDataset, EvaluationSample
from app.models.finance import Invoice, PurchaseOrder, Vendor
from app.models.identity import Membership, Organization, Role, User
from app.modules.auth.service import ensure_rbac
from app.modules.cases.service import add_comment, create_case, transition
from app.modules.documents import service as documents_service
from app.modules.exceptions.rules import ensure_default_rules
from app.modules.exceptions.service import detect_for_invoice
from app.modules.invoices.schemas import InvoiceCreate, InvoiceItemInput
from app.modules.invoices.service import create_invoice, validate_invoice
from app.modules.purchase_orders.schemas import POItemInput, PurchaseOrderCreate
from app.modules.purchase_orders.service import create_purchase_order
from app.modules.resolutions.service import create_resolution, request_approval
from app.modules.vendors.schemas import VendorCreate
from app.modules.vendors.service import create_vendor
from app.services.audit import record_audit
from app.workers.dispatch import shutdown_executor

random.seed(20260214)

DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD") or ("Aa1!" + secrets.token_urlsafe(18))
DEMO_PREFIX = "demo"

USERS = [
    ("admin@example.com", "Narin Chai", "org_admin"),
    ("manager@example.com", "Pim Srisuk", "ops_manager"),
    ("investigator@example.com", "Kanya Wong", "investigator"),
    ("approver@example.com", "Arthit Prasert", "approver"),
    ("viewer@example.com", "Lena Fischer", "viewer"),
]

VENDORS = [
    ("V-1001", "Bangkok Office Supply Co., Ltd.", "TH0105551001", "THB", "orders@bangkokoffice.example.com"),
    ("V-1002", "Siam Components Ltd.", "TH0105551002", "USD", "ap@siamcomponents.example.com"),
    ("V-1003", "Chiang Mai Logistics Co., Ltd.", "TH0105551003", "THB", "billing@cmalogs.example.com"),
    ("V-1004", "Phuket Print House", "TH0105551004", "THB", "accounts@phuketprint.example.com"),
    ("V-1005", "Northern Tools Co.", "TH0105551005", "USD", "finance@northerntools.example.com"),
    ("V-1006", "Eastern Distribution Ltd.", "TH0105551006", "USD", "invoice@easterndist.example.com"),
    ("V-1007", "Mekong Trading Co., Ltd.", "TH0105551007", "USD", "ar@mekongtrading.example.com"),
    ("V-1008", "London Advisory Partners Ltd.", "GB123456789", "GBP", "billing@londonadvisory.example.com"),
    ("V-1009", "Orchid Hospitality Group", "TH0105551009", "THB", "ap@orchidhospitality.example.com"),
    ("V-1010", "Atlas Freight Services Pte Ltd", "SG202500010", "SGD", "invoices@atlasfreight.example.com"),
]

PO_SPECS = [
    ("PO-2026-1001", 1, "Open plan furniture and monitors", "OPEN"),
    ("PO-2026-1002", 2, "Precision components batch A", "OPEN"),
    ("PO-2026-1003", 3, "Warehouse handling services", "PARTIALLY_RECEIVED"),
    ("PO-2026-1004", 4, "Marketing print run", "COMPLETED"),
    ("PO-2026-1005", 5, "Field toolkits", "OPEN"),
    ("PO-2026-1006", 6, "Bulk packaging materials", "OPEN"),
    ("PO-2026-1007", 7, "Southeast Asia distribution", "OPEN"),
    ("PO-2026-1008", 8, "Quarterly advisory retainer", "OPEN"),
    ("PO-2026-1009", 9, "Hotel venue block booking", "COMPLETED"),
    ("PO-2026-1010", 10, "Regional freight consolidation", "OPEN"),
    ("PO-2026-1011", 1, "Replacement laptop batteries", "OPEN"),
    ("PO-2026-1012", 2, "Sensor calibration kits", "OPEN"),
    ("PO-2026-1013", 3, "Cold chain monitoring", "CANCELLED"),
    ("PO-2026-1014", 4, "Annual report printing", "OPEN"),
    ("PO-2026-1015", 5, "Safety equipment renewal", "OPEN"),
    ("PO-2026-1016", 6, "Returnable pallets", "OPEN"),
    ("PO-2026-1017", 8, "Tax compliance review", "OPEN"),
    ("PO-2026-1018", 9, "Conference catering", "OPEN"),
    ("PO-2026-1019", 10, "Last-mile delivery pilot", "OPEN"),
    ("PO-2026-1020", 1, "Ergonomic chairs", "EXPIRED"),
]

CONTRACTS = [
    (1, "Master supply agreement - Bangkok Office Supply", "2024-01-01", "2026-12-31"),
    (3, "Logistics services agreement - Chiang Mai Logistics", "2024-06-01", "2025-12-31"),
    (5, "Field services agreement - Northern Tools", "2023-03-01", "2025-10-31"),
]


def _make_pdf(lines: list[str], title: str = "") -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 70
    if title:
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawString(60, y, title)
        y -= 30
    pdf.setFont("Helvetica", 10)
    for line in lines:
        pdf.drawString(60, y, line)
        y -= 18
        if y < 60:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = height - 60
    pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def _ensure_org(db) -> tuple[Organization, dict[str, User], dict[str, Membership]]:
    existing = db.scalar(select(Organization).where(Organization.slug == "northwind"))
    if existing is not None:
        raise SystemExit(
            "Demo organization 'northwind' already exists. Run `python -m app.scripts.reset_demo --yes` first."
        )
    organization = Organization(
        name="Northwind Operations",
        slug="northwind",
        legal_name="Northwind Operations Co., Ltd.",
        tax_id="TH0105559999",
        default_currency="THB",
        timezone="Asia/Bangkok",
        is_demo=True,
        branding={"accent": "#146C4F", "initials": "NO", "label": "Demo workspace"},
        settings={
            "require_purchase_order": True,
            "po_exempt_vendor_ids": [],
            "duplicate_invoice": {"absolute_tolerance": "0.00", "percentage_tolerance": "0.50"},
            "amount_mismatch": {"absolute_tolerance": "1.00", "percentage_tolerance": "1.00"},
            "approval_policy": {
                "approval_required_risk": "HIGH",
                "allow_self_approval": False,
            },
            "ai": {"investigation_enabled": True, "retrieval_top_k": 6},
            "sla_hours": {"URGENT": 8, "HIGH": 24, "MEDIUM": 48, "LOW": 72},
        },
    )
    db.add(organization)
    db.flush()
    ensure_rbac(db)
    users: dict[str, User] = {}
    memberships: dict[str, Membership] = {}
    for email, name, role_code in USERS:
        user = User(
            email=email,
            full_name=name,
            password_hash=hash_password(DEMO_PASSWORD),
            job_title=role_code.replace("_", " ").title(),
            locale="en",
        )
        db.add(user)
        db.flush()
        role = db.scalar(select(Role).where(Role.code == role_code))
        assert role is not None
        membership = Membership(org_id=organization.id, user_id=user.id, role_id=role.id)
        db.add(membership)
        db.flush()
        users[role_code] = user
        memberships[role_code] = membership
    ensure_default_rules(db, organization.id, created_by_id=users["org_admin"].id)
    db.commit()
    return organization, users, memberships


def _seed_vendors(db, organization: Organization, actor: User) -> list[Vendor]:
    vendors = []
    for number, name, tax_id, currency, email in VENDORS:
        vendor = create_vendor(
            db,
            org_id=organization.id,
            actor_id=actor.id,
            payload=VendorCreate(
                vendor_number=number,
                legal_name=name,
                tax_id=tax_id,
                currency=currency,
                email=email,
                country="TH" if tax_id.startswith("TH") else ("GB" if tax_id.startswith("GB") else "SG"),
                city="Bangkok" if tax_id.startswith("TH") else "London",
                payment_terms_days=30 if currency != "THB" else 45,
                contact_name="Accounts Payable",
            ),
        )
        db.commit()
        vendors.append(vendor)
    # Deliberate near-duplicate vendor for the duplicate-vendor rule.
    duplicate = create_vendor(
        db,
        org_id=organization.id,
        actor_id=actor.id,
        payload=VendorCreate(
            vendor_number="V-9007",
            legal_name="Mekong Trading Company Limited",
            tax_id="TH0105551007",
            currency="USD",
            email="ar2@mekongtrading.example.com",
            country="TH",
            status=VendorStatus.ACTIVE,
            risk_flags=["possible_duplicate"],
        ),
    )
    db.commit()
    vendors.append(duplicate)
    return vendors


def _seed_purchase_orders(db, organization: Organization, vendors: list[Vendor], actor: User) -> list[PurchaseOrder]:
    purchase_orders: list[PurchaseOrder] = []
    today = date.today()
    for index, (po_number, vendor_index, description, status) in enumerate(PO_SPECS):
        vendor = vendors[vendor_index - 1]
        issue_date = today - timedelta(days=120 - index * 4)
        expiration = issue_date + timedelta(days=180)
        if status == "EXPIRED":
            expiration = today - timedelta(days=30)
        unit = Decimal(random.choice(["120.00", "240.00", "380.00", "95.50", "760.00"]))
        quantity = Decimal(random.choice(["2", "3", "5", "8", "10"]))
        items = [
            POItemInput(
                description=description,
                quantity=quantity,
                unit_price=unit,
                tax_rate=Decimal("7") if vendor.currency == "THB" else Decimal("0"),
            )
        ]
        if index % 3 == 0:
            items.append(
                POItemInput(
                    description=f"{description} - additional scope",
                    quantity=Decimal("1"),
                    unit_price=unit,
                    tax_rate=Decimal("7") if vendor.currency == "THB" else Decimal("0"),
                )
            )
        po = create_purchase_order(
            db,
            org_id=organization.id,
            actor_id=actor.id,
            payload=PurchaseOrderCreate(
                po_number=po_number,
                vendor_id=vendor.id,
                currency=vendor.currency,
                issue_date=issue_date,
                expiration_date=expiration,
                status=PurchaseOrderStatus(status),
                description=description,
                items=items,
            ),
        )
        db.commit()
        purchase_orders.append(po)
    return purchase_orders


def _seed_contracts(db, organization: Organization, vendors: list[Vendor], actor: User) -> list[Document]:
    documents: list[Document] = []
    for vendor_index, title, start, expires in CONTRACTS:
        vendor = vendors[vendor_index - 1]
        lines = [
            f"Contract reference: CTR-{vendor.vendor_number}",
            f"Supplier: {vendor.legal_name}",
            f"Registered tax ID: {vendor.tax_id}",
            f"Effective date: {start}",
            f"Expiry date: {expires}",
            "Payment terms: 30 days from a valid tax invoice.",
            "Invoices must quote a purchase order reference. VAT is 7% where applicable.",
            "This agreement expires on the date stated above unless renewed in writing.",
        ]
        data = _make_pdf(lines, title=title)
        document, _ = documents_service.upload_document(
            db,
            org_id=organization.id,
            actor_id=actor.id,
            filename=f"contract_{vendor.vendor_number}.pdf",
            content_type="application/pdf",
            data=data,
            document_type=DocumentType.CONTRACT,
            vendor_id=vendor.id,
            is_demo=True,
        )
        document.metadata_ = {**(document.metadata_ or {}), "expires_on": expires, "contract_title": title}
        db.commit()
        documents_service.process_document_job(document.id, organization.id)
        db.commit()
        documents.append(document)
    return documents


def _seed_invoice_pdfs(
    db,
    organization: Organization,
    vendors: list[Vendor],
    purchase_orders: list[PurchaseOrder],
    users: dict[str, User],
    count: int,
) -> list[Invoice]:
    invoices: list[Invoice] = []
    today = date.today()
    for index in range(count):
        vendor = vendors[index % 8]
        po = next(
            (item for item in purchase_orders if item.vendor_id == vendor.id and item.status != PurchaseOrderStatus.EXPIRED),
            purchase_orders[0],
        )
        invoice_date = today - timedelta(days=random.randint(2, 70))
        subtotal = Decimal(random.choice(["480.00", "960.00", "1250.00", "2400.00", "720.00"]))
        tax_rate = Decimal("7") if vendor.currency == "THB" else Decimal("0")
        tax = (subtotal * tax_rate / Decimal("100")).quantize(Decimal("0.01"))
        total = subtotal + tax
        invoice_number = f"{vendor.vendor_number}-2026-{1000 + index}"
        lines = [
            vendor.legal_name,
            "Tax Invoice",
            f"Invoice No: {invoice_number}",
            f"Invoice Date: {invoice_date.isoformat()}",
            f"Due Date: {(invoice_date + timedelta(days=30)).isoformat()}",
            f"PO Number: {po.po_number}",
            f"Tax ID: {vendor.tax_id}",
            f"Subtotal: {subtotal}",
            f"VAT 7%: {tax}",
            f"Total: {total}",
            f"Currency: {vendor.currency}",
            "Payment Terms: Net 30",
        ]
        data = _make_pdf(lines, title="TAX INVOICE")
        document, _ = documents_service.upload_document(
            db,
            org_id=organization.id,
            actor_id=users["investigator"].id,
            filename=f"invoice_{invoice_number}.pdf",
            content_type="application/pdf",
            data=data,
            document_type=DocumentType.INVOICE,
            vendor_id=vendor.id,
            is_demo=True,
        )
        db.commit()
        documents_service.process_document_job(document.id, organization.id)
        db.commit()
        invoice = documents_service.create_invoice_from_document(
            db,
            document=document,
            actor_id=users["investigator"].id,
            vendor_id=vendor.id,
            purchase_order_id=po.id,
        )
        db.commit()
        invoices.append(invoice)
    return invoices


def _seed_manual_invoices(
    db,
    organization: Organization,
    vendors: list[Vendor],
    purchase_orders: list[PurchaseOrder],
    users: dict[str, User],
    start_index: int,
    count: int,
) -> tuple[list[Invoice], list[Invoice]]:
    invoices: list[Invoice] = []
    duplicates: list[Invoice] = []
    today = date.today()
    for index in range(count):
        vendor = vendors[index % 10]
        scenario = index % 10
        po = next(
            (item for item in purchase_orders if item.vendor_id == vendor.id),
            purchase_orders[0],
        )
        invoice_number = f"{vendor.vendor_number}-INV-{5000 + start_index + index}"
        invoice_date = today - timedelta(days=random.randint(1, 85))
        subtotal = Decimal(random.choice(["1000.00", "2400.00", "560.00", "4800.00", "1250.00"]))
        tax = (subtotal * Decimal("7") / Decimal("100")).quantize(Decimal("0.01"))
        total = subtotal + tax
        purchase_order_id = po.id
        currency = vendor.currency
        vendor_id = vendor.id
        status = InvoiceStatus.VALIDATED

        if scenario == 3:  # amount mismatch above tolerance
            total = total + Decimal("150.00")
            status = InvoiceStatus.REQUIRES_REVIEW
        elif scenario == 5:  # missing purchase order
            purchase_order_id = None
            status = InvoiceStatus.REQUIRES_REVIEW
        elif scenario == 7:  # vendor mismatch: point PO at a different vendor
            other_po = next((item for item in purchase_orders if item.vendor_id != vendor.id), po)
            purchase_order_id = other_po.id
            status = InvoiceStatus.REQUIRES_REVIEW
        elif scenario == 8:  # future invoice date
            invoice_date = today + timedelta(days=10)
            status = InvoiceStatus.REQUIRES_REVIEW
        elif scenario == 9:  # tax discrepancy
            tax = (subtotal * Decimal("10") / Decimal("100")).quantize(Decimal("0.01"))
            total = subtotal + tax
            status = InvoiceStatus.REQUIRES_REVIEW

        if index in {4, 5, 6, 7, 8, 9, 20, 21, 22}:
            status = InvoiceStatus.MATCHED
        if index in {12, 13}:
            status = InvoiceStatus.APPROVED if index == 12 else InvoiceStatus.READY_FOR_EXPORT
        if index in {30}:
            status = InvoiceStatus.REJECTED
        if index in {31}:
            status = InvoiceStatus.CANCELLED

        invoice = create_invoice(
            db,
            org_id=organization.id,
            actor_id=users["investigator"].id,
            payload=InvoiceCreate(
                invoice_number=invoice_number,
                vendor_id=vendor_id,
                purchase_order_id=purchase_order_id,
                invoice_date=invoice_date,
                due_date=invoice_date + timedelta(days=30),
                currency=currency,
                subtotal=subtotal,
                tax=tax,
                total=total,
                payment_terms_days=30,
                source="CSV" if index % 4 == 0 else "MANUAL",
                vendor_name_raw=vendor.legal_name,
                items=[
                    InvoiceItemInput(
                        description=f"Services for {invoice_date.strftime('%B %Y')}",
                        quantity=Decimal("1"),
                        unit_price=subtotal,
                        tax_rate=Decimal("7") if currency == "THB" else Decimal("0"),
                    )
                ],
                notes="Seeded demo invoice",
            ),
            status=status,
            is_demo=True,
        )
        db.commit()
        invoices.append(invoice)

    # Deliberate exact duplicates based on existing vendor/number/total.
    for source in invoices[:3]:
        duplicate = create_invoice(
            db,
            org_id=organization.id,
            actor_id=users["investigator"].id,
            payload=InvoiceCreate(
                invoice_number=source.invoice_number,
                vendor_id=source.vendor_id,
                purchase_order_id=source.purchase_order_id,
                invoice_date=source.invoice_date,
                due_date=source.due_date,
                currency=source.currency,
                subtotal=source.subtotal,
                tax=source.tax,
                total=source.total,
                payment_terms_days=source.payment_terms_days,
                source="MANUAL",
                vendor_name_raw=source.vendor_name_raw,
                notes="Duplicate submission for demo purposes",
            ),
            status=InvoiceStatus.RECEIVED,
            is_demo=True,
        )
        db.commit()
        duplicates.append(duplicate)
    return invoices, duplicates


def _seed_approvals(db, organization, cases, users):
    candidate_cases = [case for case in cases if case.status in {CaseStatus.OPEN, CaseStatus.INVESTIGATING}][:2]
    for case in candidate_cases:
        vendor = db.scalar(select(Vendor).where(Vendor.org_id == organization.id, Vendor.email.is_not(None)))
        resolution = create_resolution(
            db,
            case=case,
            actor_id=users["investigator"].id,
            action_type="REQUEST_VENDOR_CONFIRMATION",
            description="Ask the vendor to confirm the invoice total and purchase order reference.",
            parameters={
                "vendor_id": str(vendor.id),
                "message": "Please confirm the invoice amount and purchase order reference for our records.",
            },
            evidence=[],
            risk_level=RiskLevel.MEDIUM,
        )
        request_approval(
            db,
            resolution=resolution,
            requester_id=users["investigator"].id,
            assigned_approver_id=users["approver"].id,
            note="Demo approval awaiting a decision.",
        )
        case.status = CaseStatus.AWAITING_APPROVAL
        db.commit()


def _seed_history(cases, users, db):
    resolved_summaries = {
        "Duplicate invoice": "Vendor confirmed the duplicate was submitted in error; the second invoice was rejected.",
        "Amount mismatch": "Vendor issued a credit note for the difference and the invoice was re-validated.",
        "Missing purchase order": "A retroactive purchase order was approved by procurement and linked.",
        "Vendor mismatch": "Vendor master was corrected and merged after tax ID verification.",
        "Missing required documents": "Vendor supplied the missing contract and the case was closed.",
    }
    closed = 0
    for case in cases:
        if closed >= 8:
            break
        if case.status not in {CaseStatus.OPEN, CaseStatus.INVESTIGATING}:
            continue
        if not case.title:
            continue
        reason = next((value for key, value in resolved_summaries.items() if key.lower() in case.title.lower()), None)
        if reason is None:
            continue
        transition(db, case=case, new_status=CaseStatus.INVESTIGATING, actor_id=users["investigator"].id)
        transition(
            db,
            case=case,
            new_status=CaseStatus.RESOLVED,
            actor_id=users["ops_manager"].id,
            resolution_summary=reason,
        )
        transition(db, case=case, new_status=CaseStatus.CLOSED, actor_id=users["ops_manager"].id)
        db.commit()
        closed += 1


def _backdate_demo_history(db, organization: Organization) -> None:
    """Spread seeded activity across the last two months so charts and SLAs look realistic."""
    now = datetime.now(UTC)
    exceptions = db.scalars(
        select(ExceptionRecord)
        .where(ExceptionRecord.org_id == organization.id)
        .order_by(ExceptionRecord.first_detected_at)
    ).all()
    for index, record in enumerate(exceptions):
        days = (index * 7) % 68 + 1
        detected = now - timedelta(days=days, hours=(index * 3) % 12)
        record.first_detected_at = detected
        record.last_detected_at = detected + timedelta(hours=index % 6)
        record.created_at = detected
    db.flush()

    cases = db.scalars(
        select(Case).where(Case.org_id == organization.id).order_by(Case.created_at)
    ).all()
    for index, case in enumerate(cases):
        if case.status in {CaseStatus.RESOLVED, CaseStatus.CLOSED}:
            created = now - timedelta(days=(index * 7) % 52 + 6, hours=(index * 5) % 18)
            resolved = created + timedelta(hours=8 + (index % 22))
            case.created_at = created
            case.last_activity_at = resolved
            case.due_at = created + timedelta(hours=case.sla_hours)
            case.resolved_at = resolved
            case.first_response_at = created + timedelta(hours=2)
            if case.status == CaseStatus.CLOSED:
                case.closed_at = resolved + timedelta(hours=2)
            if index % 9 == 0:
                case.resolved_at = now - timedelta(hours=2)
                if case.closed_at:
                    case.closed_at = now - timedelta(hours=1)
        else:
            created = now - timedelta(hours=(index * 5) % 54 + 2)
            case.created_at = created
            case.last_activity_at = now - timedelta(hours=index % 14)
            if index % 8 == 0:
                case.due_at = now - timedelta(hours=2)
            else:
                case.due_at = now + timedelta(hours=(index % 20) + 2)
    db.flush()

    activities = db.scalars(
        select(CaseActivity)
        .join(Case, Case.id == CaseActivity.case_id)
        .where(Case.org_id == organization.id)
        .order_by(CaseActivity.created_at)
    ).all()
    for index, activity in enumerate(activities):
        case = db.get(Case, activity.case_id)
        if case is None:
            continue
        base = case.created_at or now
        activity.created_at = base + timedelta(minutes=5 * (index % 60) + 5)
    comments = db.scalars(
        select(CaseComment)
        .join(Case, Case.id == CaseComment.case_id)
        .where(Case.org_id == organization.id)
        .order_by(CaseComment.created_at)
    ).all()
    for index, comment in enumerate(comments):
        case = db.get(Case, comment.case_id)
        if case is None:
            continue
        comment.created_at = (case.created_at or now) + timedelta(hours=3 + (index % 12))
    db.commit()

def _seed_integrations(db, organization, actor):
    entries = [
        ("n8n automation", IntegrationKind.N8N, IntegrationStatus.DISABLED, {"base_url": "", "workflow_key": "case-resolution-notification"}, ["case.resolved", "approval.requested"]),
        ("Operations webhook", IntegrationKind.WEBHOOK, IntegrationStatus.UNTESTED, {"webhook_url": "", "test_method": "POST"}, ["exception.detected", "case.created"]),
        ("CSV invoice import", IntegrationKind.CSV, IntegrationStatus.CONNECTED, {"delimiter": ","}, []),
        ("MinIO documents", IntegrationKind.MINIO, IntegrationStatus.UNTESTED, {"bucket": settings.S3_BUCKET}, []),
    ]
    for name, kind, status, config, filters in entries:
        integration = Integration(
            org_id=organization.id,
            name=name,
            kind=kind,
            status=status,
            is_enabled=kind in {IntegrationKind.CSV},
            config=config,
            event_filter=filters,
            created_by_id=actor.id,
            last_error="Not configured in the seeded demo workspace." if kind in {IntegrationKind.N8N, IntegrationKind.WEBHOOK} else None,
        )
        if kind == IntegrationKind.CSV:
            integration.last_checked_at = datetime.now(UTC)
            integration.last_success_at = datetime.now(UTC)
        db.add(integration)
    db.commit()


def _seed_workflow_history(db, organization, cases, actor):
    now = datetime.now(UTC)
    for index, case in enumerate(cases[:4]):
        failed = index % 2 == 0
        execution = WorkflowExecution(
            org_id=organization.id,
            workflow_key="case-resolution-notification" if not failed else "failed-integration-recovery",
            trigger_type="EVENT",
            case_id=case.id,
            status=WorkflowStatus.FAILED if failed else WorkflowStatus.COMPLETED,
            payload={"case_number": case.case_number, "demo": True},
            result=(
                {"demo": True, "note": "Seeded demo record. No external n8n call was made."}
                if not failed
                else None
            ),
            attempts=1,
            error=(
                "No enabled n8n integration is configured. This seeded record shows how a failed run is surfaced."
                if failed
                else None
            ),
            started_at=now - timedelta(days=index + 1),
            finished_at=now - timedelta(days=index + 1) + timedelta(seconds=3),
            is_demo=True,
        )
        db.add(execution)
    db.commit()


def _seed_evaluation_dataset(db, organization, actor) -> EvaluationDataset | None:
    path = REPO_ROOT / "datasets" / "evaluation" / "investigation_samples.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    dataset = EvaluationDataset(
        org_id=organization.id,
        name=payload["name"],
        description=payload["description"],
        version=payload.get("version", "1.0"),
        is_synthetic=True,
        sample_count=len(payload["samples"]),
        created_by_id=actor.id,
    )
    db.add(dataset)
    db.flush()
    for sample in payload["samples"]:
        db.add(
            EvaluationSample(
                dataset_id=dataset.id,
                sample_key=sample["sample_key"],
                case_context=sample["case_context"],
                expected_exception_types=sample.get("expected_exception_types", []),
                expected_root_cause=sample.get("expected_root_cause", ""),
                expected_evidence=sample.get("expected_evidence", []),
                expected_recommendations=sample.get("expected_recommendations", []),
                notes=sample.get("notes"),
            )
        )
    db.commit()
    return dataset


def _seed_evaluation_run(db, organization, actor, dataset: EvaluationDataset) -> None:
    """Run a real harness pass with the configured provider (labelled stub in demo)."""
    if not settings.ai_configured:
        return
    from app.domain.enums import JobStatus
    from app.models.evaluation import EvaluationRun
    from app.modules.ai_evaluation.service import evaluate_run

    run = EvaluationRun(
        org_id=organization.id,
        dataset_id=dataset.id,
        name="Seeded baseline (real harness run)",
        provider=settings.AI_PROVIDER,
        model=settings.AI_MODEL,
        prompt_version="investigation.v1",
        retrieval_config={"top_k": settings.RETRIEVAL_TOP_K},
        status=JobStatus.QUEUED,
        sample_total=dataset.sample_count,
        created_by_id=actor.id,
    )
    db.add(run)
    db.commit()
    evaluate_run(db, run)
    db.commit()


def seed() -> dict[str, int]:
    if settings.ENV == "production":
        raise SystemExit("Refusing to seed demo data in production.")
    init_models()
    shutdown_executor()
    summary = {"vendors": 0, "purchase_orders": 0, "invoices": 0, "documents": 0, "exceptions": 0, "cases": 0}
    with SessionLocal() as db:
        organization, users, _memberships = _ensure_org(db)
        vendors = _seed_vendors(db, organization, users["org_admin"])
        summary["vendors"] = len(vendors)
        purchase_orders = _seed_purchase_orders(db, organization, vendors, users["ops_manager"])
        summary["purchase_orders"] = len(purchase_orders)
        contracts = _seed_contracts(db, organization, vendors, users["org_admin"])
        summary["documents"] += len(contracts)
        pdf_invoices = _seed_invoice_pdfs(db, organization, vendors, purchase_orders, users, 8)
        summary["invoices"] += len(pdf_invoices)
        summary["documents"] += len(pdf_invoices)
        manual_invoices, duplicates = _seed_manual_invoices(
            db, organization, vendors, purchase_orders, users, 0, 92
        )
        summary["invoices"] += len(manual_invoices) + len(duplicates)

        # Validate and detect on a realistic subset, without auto-opening 100 cases.
        target = manual_invoices[:38] + duplicates
        for invoice in target:
            validate_invoice(db, invoice=invoice, actor_id=users["investigator"].id)
            detect_for_invoice(
                db, org_id=organization.id, invoice=invoice, actor_id=users["investigator"].id,
                create_cases=False,
            )
        db.commit()

        summary["exceptions"] = db.scalar(
            select(func.count())
            .select_from(ExceptionRecord)
            .where(ExceptionRecord.org_id == organization.id)
        ) or 0

        # Open 30 cases across the highest-signal invoices.
        grouped_invoices: list[Invoice] = []
        seen_invoice_ids: set = set()
        records = db.scalars(
            select(ExceptionRecord)
            .where(ExceptionRecord.org_id == organization.id, ExceptionRecord.case_id.is_(None))
            .order_by(ExceptionRecord.severity.desc(), ExceptionRecord.last_detected_at.desc())
        ).all()
        for record in records:
            if record.entity_type != "INVOICE" or record.entity_id in seen_invoice_ids:
                continue
            seen_invoice_ids.add(record.entity_id)
            invoice = db.get(Invoice, record.entity_id)
            if invoice is not None:
                grouped_invoices.append(invoice)
            if len(grouped_invoices) >= 30:
                break

        cases: list[Case] = []
        for index, invoice in enumerate(grouped_invoices):
            exceptions = db.scalars(
                select(ExceptionRecord).where(
                    ExceptionRecord.org_id == organization.id,
                    ExceptionRecord.entity_type == "INVOICE",
                    ExceptionRecord.entity_id == invoice.id,
                )
            ).all()
            highest = Severity.HIGH if any(item.severity in {Severity.HIGH, Severity.CRITICAL} for item in exceptions) else Severity.MEDIUM
            priority = Priority.URGENT if highest == Severity.CRITICAL else (Priority.HIGH if highest == Severity.HIGH else Priority.MEDIUM)
            title_type = exceptions[0].exception_type.value.replace("_", " ").title()
            assignee = users["investigator"] if index % 2 == 0 else users["ops_manager"]
            case = create_case(
                db,
                org_id=organization.id,
                actor_id=users["ops_manager"].id,
                title=f"{title_type} – {invoice.invoice_number}",
                description="Automatically opened from detected invoice exceptions.",
                priority=priority,
                severity=highest,
                assigned_user_id=assignee.id,
                tags=["demo", exceptions[0].exception_type.value.lower()],
                links=[("INVOICE", invoice.id, invoice.invoice_number)],
                exception_ids=[item.id for item in exceptions],
                notify_team=False,
            )
            status_cycle = index % 10
            if status_cycle in {1, 2}:
                transition(db, case=case, new_status=CaseStatus.INVESTIGATING, actor_id=assignee.id)
            elif status_cycle == 3:
                transition(db, case=case, new_status=CaseStatus.AWAITING_INFORMATION, actor_id=assignee.id)
            elif status_cycle == 4:
                add_comment(
                    db,
                    case=case,
                    author=assignee,
                    body="Requested the vendor confirmation; waiting for the AP mailbox.",
                )
                transition(db, case=case, new_status=CaseStatus.INVESTIGATING, actor_id=assignee.id)
            elif status_cycle == 5 and index < 12:
                transition(db, case=case, new_status=CaseStatus.RESOLUTION_IN_PROGRESS, actor_id=assignee.id)
            cases.append(case)
            db.commit()

        headings = [case.title.split(" – ")[0] for case in cases]
        for case, heading in zip(cases, headings, strict=False):
            comment_body = (
                f"Investigated {heading.lower()}. Compared the invoice, purchase order and vendor master; "
                "the figures were checked deterministically."
            )
            add_comment(db, case=case, author=users["investigator"], body=comment_body)
        db.commit()

        _seed_history(cases, users, db)
        _backdate_demo_history(db, organization)
        _seed_approvals(db, organization, cases, users)
        _seed_integrations(db, organization, users["org_admin"])
        _seed_workflow_history(db, organization, cases, users["ops_manager"])
        eval_dataset = _seed_evaluation_dataset(db, organization, users["org_admin"])
        if eval_dataset is not None:
            _seed_evaluation_run(db, organization, users["org_admin"], eval_dataset)

        record_audit(
            db,
            org_id=organization.id,
            action="demo.seeded",
            entity_type="organization",
            entity_id=organization.id,
            summary="Demo workspace seeded with synthetic data",
            actor=users["org_admin"],
            after=summary,
        )
        db.commit()
        summary["cases"] = len(cases)
        summary["documents"] = db.scalar(
            select(func.count())
            .select_from(Document)
            .where(Document.org_id == organization.id)
        ) or summary["documents"]
        print(json.dumps({"organization": organization.slug, "password": DEMO_PASSWORD, **summary}, indent=2))
        print("\nDemo users:")
        for email, _name, role in USERS:
            print(f"  {email:32s} {role:18s} {DEMO_PASSWORD}")
        return summary


if __name__ == "__main__":
    seed()
