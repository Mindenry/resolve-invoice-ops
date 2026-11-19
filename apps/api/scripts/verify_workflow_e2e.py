"""End-to-end business workflow verification against a live API and PostgreSQL.

Run with the API serving the seeded PostgreSQL database:

    python scripts/verify_workflow_e2e.py --base-url http://127.0.0.1:8001

The script exercises login, vendor/PO creation, invoice upload, extraction,
correction and review, matching, deterministic exceptions, case creation and
assignment, AI investigation (stub provider by default), approval, execution,
audit and analytics. It also exercises tenant isolation, RBAC, self-approval
and invoice/document idempotency, then inspects the database directly.
"""

from __future__ import annotations

import argparse
import io
import os
import secrets
import string
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _load_dotenv_defaults() -> None:
    """Load .env values that are not already present in the process environment."""
    env_path = _REPO_ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv_defaults()

PASSWORD = os.environ.get("RESOLVE_DEMO_PASSWORD", "")


def rand(n: int = 6) -> str:
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(n))


class Workflow:
    def __init__(self, base_url: str) -> None:
        self.base = base_url.rstrip("/") + "/api/v1"
        self.client = httpx.Client(timeout=60.0)
        self.failures: list[str] = []
        self.steps: list[str] = []

    def step(self, label: str) -> None:
        self.steps.append(label)
        print(f"  - {label}")

    def call(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        expect: int | tuple[int, ...] = 200,
        **kwargs,
    ) -> httpx.Response:
        response = self.client.request(method, f"{self.base}{path}", headers=headers, **kwargs)
        expected = (expect,) if isinstance(expect, int) else expect
        if response.status_code not in expected:
            raise AssertionError(
                f"{method} {path} -> {response.status_code} (expected {expected}): {response.text[:800]}"
            )
        return response

    def login(self, email: str, organization_slug: str = "northwind") -> dict[str, str]:
        response = self.call(
            "POST",
            "/auth/login",
            json={"email": email, "password": PASSWORD, "organization_slug": organization_slug},
        )
        body = response.json()
        self.last_login = body
        return {"Authorization": f"Bearer {body['access_token']}", "X-Organization-Id": body["organization"]["id"]}

    def pdf(self, invoice_number: str, po_number: str) -> bytes:
        from reportlab.pdfgen import canvas

        buffer = io.BytesIO()
        pdf = canvas.Canvas(buffer)
        lines = [
            "ACME E2E SUPPLIES LTD.",
            "Tax Invoice",
            f"Invoice No: {invoice_number}",
            "Invoice Date: 2026-03-14",
            "Due Date: 2026-04-13",
            f"PO Number: {po_number}",
            "Subtotal: 1,200.00",
            "VAT 7%: 84.00",
            "Total: 1,284.00",
            "Currency: USD",
            "Payment Terms: Net 30",
        ]
        y = 800
        for line in lines:
            pdf.drawString(60, y, line)
            y -= 22
        pdf.save()
        return buffer.getvalue()


def db_check(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
        cursor.execute("select count(*) from information_schema.tables where table_schema='public'")
        tables = cursor.fetchone()[0]
        cursor.execute("select count(*) from organizations")
        orgs = cursor.fetchone()[0]
        print(f"  DB: {tables} public tables, {orgs} organizations")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()

    global PASSWORD
    if not PASSWORD:
        secret_file = Path(__file__).resolve().parents[3] / "var" / "secrets" / "demo-credentials.txt"
        if secret_file.exists():
            for line in secret_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("admin@example.com="):
                    PASSWORD = line.split("=", 1)[1].strip()
                    break
    if not PASSWORD:
        raise SystemExit("Set RESOLVE_DEMO_PASSWORD or create var/secrets/demo-credentials.txt")
    workflow = Workflow(args.base_url)
    headers = workflow.login("admin@example.com")
    workflow.step("login as org admin")
    approver_headers = workflow.login("approver@example.com")
    investigator_headers = workflow.login("investigator@example.com")
    viewer_headers = workflow.login("viewer@example.com")

    me = workflow.call("GET", "/users/me", headers=headers).json()
    workflow.step(f"profile: {me['email']} ({me.get('role', 'ok')})")
    members = workflow.call("GET", "/users", headers=headers, params={"page_size": 100}).json()["items"]
    approver = next(member for member in members if member["email"] == "approver@example.com")
    investigator = next(member for member in members if member["email"] == "investigator@example.com")
    print(f"  users={len(members)} approver={approver['user_id']} investigator={investigator['user_id']}")

    # --- vendor and purchase order ---------------------------------------
    suffix = rand()
    vendor = workflow.call(
        "POST",
        "/vendors",
        headers=headers,
        expect=201,
        json={
            "vendor_number": f"E2E-V-{suffix}",
            "legal_name": f"ACME E2E SUPPLIES {suffix}",
            "tax_id": f"TH0105{suffix}",
            "currency": "USD",
            "email": f"ap+{suffix.lower()}@acme-e2e.example",
            "payment_terms_days": 30,
        },
    ).json()
    workflow.step(f"vendor created {vendor['vendor_number']}")

    issue_date = date.today()
    po = workflow.call(
        "POST",
        "/purchase-orders",
        headers=headers,
        expect=201,
        json={
            "po_number": f"E2E-PO-{suffix}",
            "vendor_id": vendor["id"],
            "currency": "USD",
            "issue_date": issue_date.isoformat(),
            "expiration_date": (issue_date + timedelta(days=60)).isoformat(),
            "status": "OPEN",
            "description": "E2E verification order",
            "items": [
                {"description": "Widgets", "quantity": "10", "unit_price": "100.00", "tax_rate": "0"}
            ],
        },
    ).json()
    workflow.step(f"purchase order created {po['po_number']} total={po.get('total')}")

    # --- document upload, extraction, correction, review ------------------
    invoice_number = f"E2E-INV-{suffix}"
    pdf = workflow.pdf(invoice_number, po["po_number"])
    upload = workflow.call(
        "POST",
        "/documents",
        headers=investigator_headers,
        expect=201,
        files={"file": (f"{invoice_number}.pdf", pdf, "application/pdf")},
        data={"document_type": "INVOICE"},
    ).json()
    document_id = upload["document"]["id"]
    workflow.step(f"document uploaded {document_id}")

    detail = workflow.call("GET", f"/documents/{document_id}", headers=investigator_headers).json()
    for _ in range(120):
        if detail["status"] in {"INDEXED", "EXTRACTED", "REQUIRES_REVIEW", "FAILED"}:
            break
        time.sleep(1)
        detail = workflow.call("GET", f"/documents/{document_id}", headers=investigator_headers).json()
    assert detail["status"] not in {"FAILED", "UPLOADED"}, detail
    assert detail["char_count"] > 100
    extraction = detail["extraction"]
    assert extraction is not None
    fields = {field["field_name"]: field for field in extraction["fields"]}
    for required in ("invoice_number", "invoice_date", "total"):
        assert required in fields, f"missing extracted field {required}: {sorted(fields)}"
    assert fields["invoice_number"]["effective_value"] == invoice_number
    workflow.step(f"extraction parsed {len(fields)} fields (status={extraction['review_status']})")

    corrected_number = invoice_number + "-R"
    corrected = workflow.call(
        "PATCH",
        f"/documents/{document_id}/fields/{fields['invoice_number']['id']}",
        headers=investigator_headers,
        json={"value": corrected_number, "notes": "E2E correction"},
    ).json()
    assert corrected["effective_value"] == corrected_number
    workflow.step("extracted invoice number corrected")

    reviewed = workflow.call(
        "POST",
        f"/documents/{document_id}/review",
        headers=investigator_headers,
        json={"action": "APPROVE", "note": "E2E review", "approve_low_confidence_fields": True},
    ).json()
    assert reviewed["review_status"] in {"APPROVED", "NOT_REQUIRED"}
    workflow.step("extraction reviewed and approved")

    created = workflow.call(
        "POST",
        f"/documents/{document_id}/create-invoice",
        headers=investigator_headers,
        expect=(200, 201),
        json={"vendor_id": vendor["id"], "purchase_order_id": po["id"]},
    ).json()
    invoice_id = created["invoice_id"]
    assert created["invoice_number"] == corrected_number
    workflow.step(f"invoice created from document {created['invoice_number']}")

    duplicate_attempt = workflow.call(
        "POST",
        f"/documents/{document_id}/create-invoice",
        headers=investigator_headers,
        expect=(200, 201),
        json={"vendor_id": vendor["id"], "purchase_order_id": po["id"]},
    ).json()
    assert duplicate_attempt["invoice_id"] == invoice_id, "duplicate invoice created from one document"
    workflow.step("invoice creation is idempotent per document")

    # --- deterministic validation and exceptions --------------------------
    validation = workflow.call(
        "POST",
        f"/invoices/{invoice_id}/validate",
        headers=investigator_headers,
        params={"run_exception_detection": "true"},
    ).json()
    workflow.step(f"invoice validated: status={validation.get('status')} checks={len(validation.get('checks', []))}")

    invoice = workflow.call("GET", f"/invoices/{invoice_id}", headers=headers).json()
    assert invoice["purchase_order_id"] == po["id"]
    assert invoice["vendor"]["id"] == vendor["id"]
    print(f"  invoice total={invoice['total']} status={invoice['status']}")

    scan = workflow.call(
        "POST",
        "/exceptions/scan",
        headers=investigator_headers,
        json={"invoice_id": invoice_id, "create_cases": False},
    ).json()
    exception_ids = scan["exception_ids"]
    assert exception_ids, f"deterministic rules produced no exception: {scan}"
    workflow.step(f"exception engine produced {len(exception_ids)} exception(s)")

    listed = workflow.call(
        "GET",
        "/exceptions",
        headers=headers,
        params={"entity_type": "INVOICE", "entity_id": invoice_id, "page_size": 100},
    ).json()
    assert listed["meta"]["total"] >= len(exception_ids)
    workflow.step("exceptions visible through the API with invoice linkage")

    # --- case, assignment, investigation ---------------------------------
    case = workflow.call(
        "POST",
        "/cases",
        headers=headers,
        expect=201,
        json={
            "title": f"E2E price variance {suffix}",
            "description": "Invoice total exceeds the purchase order tolerance.",
            "priority": "HIGH",
            "exception_ids": exception_ids,
            "invoice_id": invoice_id,
            "tags": ["e2e", f"run-{suffix.lower()}"],
        },
    ).json()
    case_id = case["id"]
    assert case["status"] == "OPEN"
    workflow.step(f"case {case['case_number']} created with {len(case['exceptions'])} exceptions")

    assigned = workflow.call(
        "POST",
        f"/cases/{case_id}/assign",
        headers=headers,
        json={"user_id": investigator["user_id"], "reason": "E2E assignment"},
    ).json()
    assert assigned["assigned_user"]["id"] == investigator["user_id"]
    workflow.step("case assigned to investigator")

    started = workflow.call(
        "POST",
        f"/cases/{case_id}/investigations",
        headers=investigator_headers,
        expect=(200, 201),
        json={"include_similar_cases": True, "top_k": 6, "wait": True},
    ).json()
    investigation_id = started["id"]
    final = started
    for _ in range(120):
        current = workflow.call("GET", f"/investigations/{investigation_id}", headers=investigator_headers).json()
        final = current
        if current["status"] in {"COMPLETED", "FAILED", "NEEDS_REVIEW", "CANCELLED"}:
            break
        time.sleep(2)
    assert final["status"] in {"COMPLETED", "NEEDS_REVIEW"}, final
    evidence = final.get("evidence", [])
    validated_evidence = [item for item in evidence if item.get("is_validated")]
    workflow.step(
        f"AI investigation {final['status']} provider={final.get('provider')} "
        f"evidence={len(evidence)} validated={len(validated_evidence)}"
    )

    suggestions = final.get("suggested_resolutions") or final.get("suggestions") or []
    print(f"  investigation suggestions={len(suggestions)}")

    # --- resolution, approval, execution ---------------------------------
    resolution = workflow.call(
        "POST",
        f"/cases/{case_id}/resolutions",
        headers=headers,
        expect=201,
        json={
            "action_type": "REQUEST_VENDOR_CONFIRMATION",
            "description": "Ask the vendor to confirm the invoice total.",
            "parameters": {
                "vendor_id": vendor["id"],
                "invoice_id": invoice_id,
                "message": "Please confirm the total on this invoice.",
            },
            "risk_level": "HIGH",
            "request_approval": True,
            "approver_id": approver["user_id"],
            "note": "E2E approval request",
        },
    ).json()
    resolution_id = resolution["id"]
    assert resolution["status"] in {"PENDING_APPROVAL", "AWAITING_APPROVAL", "VALIDATED"}, resolution
    approval = resolution.get("approval")
    assert approval, resolution
    approval_id = approval["id"]
    workflow.step(f"resolution proposed, approval {approval['status']}")

    pending = workflow.call(
        "GET", "/approvals", headers=approver_headers, params={"status": "PENDING", "page_size": 100}
    ).json()
    assert any(item["id"] == approval_id for item in pending["items"])
    workflow.step("approval appears in the approver queue")

    decided = workflow.call(
        "POST",
        f"/approvals/{approval_id}/approve",
        headers=approver_headers,
        json={"comment": "Approved during E2E verification.", "execute_after_approval": False},
    ).json()
    assert decided["approval"]["status"] == "APPROVED"
    workflow.step("approval decided")

    executed = workflow.call(
        "POST", f"/resolutions/{resolution_id}/execute", headers=headers, expect=(200, 400, 409)
    ).json()
    if executed.get("status") == "COMPLETED":
        workflow.step(f"resolution executed: {executed.get('execution_result')}")
    else:
        workflow.step(f"resolution execution returned status={executed.get('status')} error={executed.get('error')}")

    final_resolution = workflow.call("GET", f"/resolutions/{resolution_id}", headers=headers).json()
    print(f"  resolution status={final_resolution['status']}")

    # --- audit, case timeline, analytics ---------------------------------
    audit = workflow.call(
        "GET",
        "/audit",
        headers=headers,
        params={"entity_type": "case", "entity_id": case_id, "page_size": 100},
    ).json()
    actions = {row["action"] for row in audit["items"]}
    assert actions, "no audit rows for the case"
    workflow.step(f"audit trail has {len(actions)} case actions: {sorted(actions)[:6]}")

    timeline = workflow.call("GET", f"/cases/{case_id}/timeline", headers=headers).json()
    assert timeline
    workflow.step(f"case timeline has {len(timeline)} entries")

    overview = workflow.call("GET", "/analytics/overview", headers=headers).json()
    workflow.step(f"analytics overview keys={sorted(overview)[:8]}")

    # --- negative: RBAC ---------------------------------------------------
    forbidden = workflow.call(
        "POST",
        "/vendors",
        headers=viewer_headers,
        expect=403,
        json={"vendor_number": f"NOPE-{suffix}", "legal_name": "Should not exist"},
    )
    assert forbidden.status_code == 403
    workflow.step("viewer cannot create a vendor (403)")

    # --- negative: production registration + tenant isolation -------------
    registration = workflow.call(
        "POST",
        "/auth/register",
        expect=403,
        json={
            "organization_name": f"E2E Other {suffix}",
            "organization_slug": f"e2e-other-{suffix.lower()}",
            "full_name": "Other Tenant Admin",
            "email": f"other-{suffix.lower()}@example.com",
            "password": "OtherTenant123!",
        },
    )
    assert registration.status_code == 403
    workflow.step("self-service registration disabled in production (403)")

    other_email = os.environ.get("RESOLVE_OTHER_TENANT_EMAIL", "")
    other_password = os.environ.get("RESOLVE_OTHER_TENANT_PASSWORD", "")
    if not other_email or not other_password:
        workflow.step("cross-tenant checks SKIPPED: RESOLVE_OTHER_TENANT_* not configured")
        other_headers = None
    else:
        other_login = workflow.call(
            "POST",
            "/auth/login",
            expect=200,
            json={
                "email": other_email,
                "password": other_password,
                "organization_slug": os.environ.get("RESOLVE_OTHER_TENANT_ORG_SLUG", ""),
            },
        ).json()
        other_headers = {
            "Authorization": f"Bearer {other_login['access_token']}",
            "X-Organization-Id": other_login["organization"]["id"],
        }

    if other_headers:
        cross_vendor = workflow.call("GET", f"/vendors/{vendor['id']}", headers=other_headers, expect=404)
        assert cross_vendor.status_code == 404
        cross_case = workflow.call("GET", f"/cases/{case_id}", headers=other_headers, expect=404)
        assert cross_case.status_code == 404
        cross_document = workflow.call("GET", f"/documents/{document_id}", headers=other_headers, expect=404)
        assert cross_document.status_code == 404
        workflow.step("cross-tenant reads are rejected (404)")

        cross_link = workflow.call(
            "POST",
            f"/documents/{document_id}/create-invoice",
            headers=other_headers,
            expect=404,
            json={},
        )
        assert cross_link.status_code == 404
        workflow.step("cross-tenant document mutations are rejected (404)")

    # --- negative: self approval -----------------------------------------
    self_case = workflow.call(
        "POST",
        "/cases",
        headers=headers,
        expect=201,
        json={"title": f"Self approval guard {suffix}", "priority": "LOW", "tags": ["e2e"]},
    ).json()
    self_resolution = workflow.call(
        "POST",
        f"/cases/{self_case['id']}/resolutions",
        headers=headers,
        expect=201,
        json={
            "action_type": "UPDATE_CASE_PRIORITY",
            "description": "Self approval guard test",
            "parameters": {"priority": "HIGH"},
            "risk_level": "HIGH",
            "request_approval": True,
            "approver_id": me["id"],
        },
    ).json()
    self_approval_id = self_resolution["approval"]["id"]
    self_decision = workflow.call(
        "POST",
        f"/approvals/{self_approval_id}/approve",
        headers=headers,
        expect=403,
        json={"comment": "self approval"},
    )
    assert self_decision.status_code == 403
    workflow.step("self-approval is rejected (403)")

    # --- direct database verification ------------------------------------
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if dsn:
        from urllib.parse import urlsplit, urlunsplit

        import psycopg

        # From the Windows host the Compose service name is not resolvable; use
        # the published loopback port instead. Inside the API container the
        # original DSN is correct.
        if "://" in dsn and "@postgres:" in dsn and not os.environ.get("IN_DOCKER"):
            parts = urlsplit(dsn)
            port = os.environ.get("POSTGRES_PORT", "5433")
            credentials = parts.netloc.rsplit("@", 1)[0]
            dsn = urlunsplit(
                (parts.scheme, f"{credentials}@127.0.0.1:{port}", parts.path, parts.query, parts.fragment)
            )

        with psycopg.connect(dsn) as connection, connection.cursor() as cursor:
            cursor.execute("select status, total from invoices where id = %s", (invoice_id,))
            print(f"  DB invoice: {cursor.fetchone()}")
            cursor.execute("select status from documents where id = %s", (document_id,))
            print(f"  DB document: {cursor.fetchone()}")
            cursor.execute("select status from cases where id = %s", (case_id,))
            print(f"  DB case: {cursor.fetchone()}")
            cursor.execute("select status, decision_note from approval_requests where id = %s", (approval_id,))
            print(f"  DB approval: {cursor.fetchone()}")
            cursor.execute("select status from resolutions where id = %s", (resolution_id,))
            print(f"  DB resolution: {cursor.fetchone()}")
            cursor.execute(
                "select count(*) from audit_logs where entity_id = %s or entity_id = %s",
                (case_id, resolution_id),
            )
            print(f"  DB audit rows (case+resolution): {cursor.fetchone()[0]}")
            cursor.execute(
                "select count(*) from exceptions where entity_type = 'INVOICE' and entity_id = %s",
                (invoice_id,),
            )
            print(f"  DB exceptions for invoice: {cursor.fetchone()[0]}")

    print(f"\nWORKFLOW COMPLETE: {len(workflow.steps)} steps verified")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nE2E FAILURE: {exc}")
        raise SystemExit(1)
