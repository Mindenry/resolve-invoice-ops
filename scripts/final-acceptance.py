"""Final RESOLVE acceptance suite: roles, financial edge cases, security and retries.

Runs against the live HTTPS deployment, writes a Markdown evidence table to
docs/FINAL_ACCEPTANCE_RESULTS.md, and exits non-zero if any executed case fails.
No secret is printed.
"""

from __future__ import annotations

import io
import subprocess
import time
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw

LAN = os.environ.get("RESOLVE_WEB_URL", "https://localhost:8180")
API = f"{LAN}/api/v1"
VERIFY = "var/certs/rootCA.pem"
ORG = "northwind"
RESULTS: list[dict[str, str]] = []


def env() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def creds() -> dict[str, str]:
    data: dict[str, str] = {}
    for line in Path("var/secrets/demo-credentials.txt").read_text(encoding="utf-8").splitlines():
        if "=" in line and "@" in line:
            email, password = line.split("=", 1)
            data[email.strip()] = password.strip()
    return data


def record(case_id: str, scenario: str, expected: str, passed: bool, actual: str, evidence: str = "") -> None:
    RESULTS.append(
        {
            "id": case_id,
            "scenario": scenario,
            "expected": expected,
            "actual": actual,
            "status": "PASS" if passed else "FAIL",
            "evidence": evidence,
        }
    )
    print(f"{'PASS' if passed else 'FAIL'} {case_id} {scenario} :: {actual}")


class Api:
    def __init__(self) -> None:
        self.client = httpx.Client(verify=VERIFY, timeout=90)

    def call(self, method: str, path: str, headers: dict | None = None, **kwargs: Any) -> httpx.Response:
        return self.client.request(method, f"{API}{path}", headers=headers, **kwargs)

    def login(self, email: str, password: str, slug: str = ORG) -> dict:
        response = self.client.post(
            f"{API}/auth/login",
            json={"email": email, "password": password, "organization_slug": slug},
        )
        if response.status_code != 200:
            raise SystemExit(f"login failed for {email}: {response.status_code} {response.text[:200]}")
        return response.json()

    def headers(self, session: dict) -> dict:
        return {
            "Authorization": f"Bearer {session['access_token']}",
            "X-Organization-Id": session["organization"]["id"],
        }


def exceptions_for(api: Api, headers: dict, invoice_id: str) -> list[dict]:
    response = api.call(
        "GET", "/exceptions", headers=headers, params={"entity_id": invoice_id, "page_size": 100}
    )
    response.raise_for_status()
    return response.json().get("items", [])


def types_of(items: list[dict]) -> set[str]:
    return {item["exception_type"] for item in items}


def create_vendor(api: Api, headers: dict, suffix: str, name: str, tax: str | None = None) -> dict:
    response = api.call(
        "POST",
        "/vendors",
        headers=headers,
        json={
            "vendor_number": f"FA-{uuid.uuid4().hex[:10].upper()}",
            "legal_name": name,
            "tax_id": tax,
            "currency": "USD",
            "email": f"{name[:5].lower().replace(' ', '')}-{suffix.lower()}@example.com",
        },
    )
    response.raise_for_status()
    return response.json()


def create_po(api: Api, headers: dict, suffix: str, vendor_id: str, total: str, status: str = "OPEN") -> dict:
    qty = "10" if total == "1000.00" else "1"
    price = "100.00" if total == "1000.00" else total
    response = api.call(
        "POST",
        "/purchase-orders",
        headers=headers,
        json={
            "po_number": f"FA-PO-{suffix}-{uuid.uuid4().hex[:4].upper()}",
            "vendor_id": vendor_id,
            "currency": "USD",
            "issue_date": date.today().isoformat(),
            "status": status,
            "items": [{"description": "Acceptance item", "quantity": qty, "unit_price": price, "tax_rate": "0"}],
        },
    )
    response.raise_for_status()
    return response.json()


def create_invoice(api: Api, headers: dict, suffix: str, **overrides: Any) -> httpx.Response:
    payload: dict[str, Any] = {
        "invoice_number": f"FA-{suffix}",
        "invoice_date": date.today().isoformat(),
        "currency": "USD",
        "subtotal": "100.00",
        "tax": "0.00",
        "total": "100.00",
        "source": "MANUAL",
        "items": [
            {"description": "Acceptance item", "quantity": "1", "unit_price": "100.00", "tax_rate": "0"}
        ],
    }
    payload.update(overrides)
    return api.call("POST", "/invoices", headers=headers, json=payload)


def validate(api: Api, headers: dict, invoice_id: str) -> dict:
    response = api.call("POST", f"/invoices/{invoice_id}/validate", headers=headers)
    response.raise_for_status()
    return response.json()


def upload(api: Api, headers: dict, name: str, content: bytes, mime: str, doc_type: str = "INVOICE") -> httpx.Response:
    return api.call(
        "POST",
        "/documents",
        headers=headers,
        files={"file": (name, io.BytesIO(content), mime)},
        data={"document_type": doc_type},
    )


def poll_document(api: Api, headers: dict, doc_id: str, timeout: int = 120) -> dict:
    deadline = time.time() + timeout
    last: dict = {}
    while time.time() < deadline:
        response = api.call("GET", f"/documents/{doc_id}", headers=headers)
        if response.status_code == 200:
            last = response.json()
            if last.get("status") in {"INDEXED", "EXTRACTED", "FAILED", "REQUIRES_REVIEW"}:
                return last
        time.sleep(2)
    return last


def make_case_with_approval(api: Api, headers: dict, suffix: str, approver_id: str, label: str) -> tuple[str, str, str]:
    case = api.call(
        "POST",
        "/cases",
        headers=headers,
        json={"title": f"Acceptance {label} {suffix}", "priority": "HIGH", "tags": ["acceptance"]},
    ).json()
    resolution = api.call(
        "POST",
        f"/cases/{case['id']}/resolutions",
        headers=headers,
        json={
            "action_type": "UPDATE_CASE_PRIORITY",
            "description": f"{label} acceptance check",
            "parameters": {"priority": "MEDIUM"},
            "risk_level": "HIGH",
            "request_approval": True,
            "approver_id": approver_id,
            "note": label,
        },
    )
    if resolution.status_code >= 400:
        raise RuntimeError(f"resolution failed: {resolution.status_code} {resolution.text[:200]}")
    body = resolution.json()
    approval = body.get("approval") or {}
    return case["id"], body["id"], approval.get("id", "")


def sql(query: str) -> str:
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "resolve", "-d", "resolve", "-t", "-A", "-c", query],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip()


def main() -> int:
    env_values = env()
    passwords = creds()
    api = Api()
    suffix = datetime.now(UTC).strftime("%H%M%S")

    sessions = {}
    for label, email in [
        ("org_admin", "admin@example.com"),
        ("ops_manager", "manager@example.com"),
        ("investigator", "investigator@example.com"),
        ("approver", "approver@example.com"),
        ("viewer", "viewer@example.com"),
        ("super_admin", "superadmin@example.com"),
        ("automation", "automation@example.com"),
    ]:
        if email in passwords:
            sessions[label] = api.login(email, passwords[email])
    if "automation" not in sessions and env_values.get("RESOLVE_AUTOMATION_EMAIL"):
        sessions["automation"] = api.login(
            env_values["RESOLVE_AUTOMATION_EMAIL"],
            env_values["RESOLVE_AUTOMATION_PASSWORD"],
            env_values.get("RESOLVE_ORGANIZATION_SLUG", ORG),
        )

    headers = api.headers(sessions["org_admin"])
    approver_headers = api.headers(sessions["approver"])
    approver_id = sessions["approver"]["user"]["id"]

    # ---------------------------------------------------------------- setup
    vendor_a = create_vendor(api, headers, suffix, "Acceptance Alpha")
    vendor_b = create_vendor(api, headers, suffix, "Acceptance Beta")
    vendor_c = create_vendor(api, headers, suffix, "Acceptance Gamma", tax="TH-GAMMA-001")
    vendor_c2 = create_vendor(api, headers, suffix, "Acceptance Gamma Two", tax="TH-GAMMA-999")
    po_a = create_po(api, headers, suffix, vendor_a["id"], "1000.00")
    po_c = create_po(api, headers, suffix, vendor_c["id"], "1000.00")

    # ------------------------------------------------------------ F01..F12
    inv1 = create_invoice(api, headers, f"F01-{suffix}", vendor_id=vendor_a["id"]).json()
    validate(api, headers, inv1["id"])
    inv2 = create_invoice(api, headers, f"F01-{suffix}", vendor_id=vendor_a["id"]).json()
    validate(api, headers, inv2["id"])
    types2 = types_of(exceptions_for(api, headers, inv2["id"]))
    record("F01", "Duplicate invoice (same vendor/number/amount)", "DUPLICATE_INVOICE detected",
           "DUPLICATE_INVOICE" in types2, f"types={sorted(types2)}", f"invoice={inv2['id']}")

    inv3 = create_invoice(api, headers, f"F01-{suffix}", vendor_id=vendor_b["id"]).json()
    validate(api, headers, inv3["id"])
    types3 = types_of(exceptions_for(api, headers, inv3["id"]))
    record("F02", "Same invoice number, different vendor", "No duplicate exception",
           "DUPLICATE_INVOICE" not in types3, f"types={sorted(types3)}", f"invoice={inv3['id']}")

    inv4 = create_invoice(
        api, headers, f"F03-{suffix}", vendor_id=vendor_a["id"], purchase_order_id=po_a["id"],
        subtotal="500.00", total="500.00",
        items=[{"description": "x", "quantity": "1", "unit_price": "500.00", "tax_rate": "0"}],
    ).json()
    validate(api, headers, inv4["id"])
    types4 = types_of(exceptions_for(api, headers, inv4["id"]))
    record("F03", "Invoice amount differs from PO", "AMOUNT_MISMATCH detected",
           "AMOUNT_MISMATCH" in types4, f"types={sorted(types4)}", f"invoice={inv4['id']}")

    inv5 = create_invoice(
        api, headers, f"F04-{suffix}", vendor_id=vendor_a["id"],
        subtotal="100.00", tax="12.00", total="112.00",
        items=[{"description": "x", "quantity": "1", "unit_price": "100.00", "tax_rate": "10"}],
    ).json()
    validation5 = validate(api, headers, inv5["id"])
    types5 = types_of(exceptions_for(api, headers, inv5["id"]))
    check_codes = {c["code"] for c in validation5["checks"]}
    record("F04", "VAT calculated incorrectly (12% implied, 10% line)",
           "TAX_DISCREPANCY + line_tax_mismatch",
           "TAX_DISCREPANCY" in types5 and "line_tax_mismatch" in check_codes,
           f"types={sorted(types5)} checks={sorted(check_codes)}", f"invoice={inv5['id']}")

    inv6 = create_invoice(api, headers, f"F05-{suffix}", vendor_id=vendor_b["id"], purchase_order_id=po_a["id"]).json()
    validate(api, headers, inv6["id"])
    types6 = types_of(exceptions_for(api, headers, inv6["id"]))
    record("F05", "Vendor differs from PO vendor", "VENDOR_MISMATCH detected",
           "VENDOR_MISMATCH" in types6, f"types={sorted(types6)}", f"invoice={inv6['id']}")

    inv7 = create_invoice(api, headers, f"F06-{suffix}", vendor_id=vendor_a["id"]).json()
    validate(api, headers, inv7["id"])
    types7 = types_of(exceptions_for(api, headers, inv7["id"]))
    record("F06", "Missing purchase order", "MISSING_PURCHASE_ORDER detected",
           "MISSING_PURCHASE_ORDER" in types7, f"types={sorted(types7)}", f"invoice={inv7['id']}")
    record("F07", "Missing supporting documents", "MISSING_DOCUMENTS detected",
           "MISSING_DOCUMENTS" in types7, f"types={sorted(types7)}", f"invoice={inv7['id']}")

    future = (date.today() + timedelta(days=5)).isoformat()
    inv8 = create_invoice(api, headers, f"F08-{suffix}", vendor_id=vendor_a["id"], invoice_date=future).json()
    validation8 = validate(api, headers, inv8["id"])
    codes8 = {c["code"] for c in validation8["checks"]}
    types8 = types_of(exceptions_for(api, headers, inv8["id"]))
    record("F08", "Invalid (future) invoice date", "future_invoice_date + INVALID_INVOICE_DATE",
           "future_invoice_date" in codes8 and "INVALID_INVOICE_DATE" in types8,
           f"checks={sorted(codes8)} types={sorted(types8)}", f"invoice={inv8['id']}")

    inv9 = create_invoice(api, headers, f"F09-{suffix}", vendor_id=vendor_c2["id"], purchase_order_id=po_c["id"]).json()
    validate(api, headers, inv9["id"])
    exc9 = exceptions_for(api, headers, inv9["id"])
    mismatch9 = next((e for e in exc9 if e["exception_type"] == "VENDOR_MISMATCH"), None)
    record("F09", "Invalid tax information (vendor identity differs from PO)",
           "VENDOR_MISMATCH blocks the invoice",
           mismatch9 is not None,
           f"types={sorted(types_of(exc9))} description={(mismatch9 or {}).get('description', '')[:60]}",
           f"invoice={inv9['id']}")

    inv10 = create_invoice(api, headers, f"F10-{suffix}", vendor_id=vendor_a["id"], purchase_order_id=po_a["id"], currency="EUR").json()
    validation10 = validate(api, headers, inv10["id"])
    codes10 = {c["code"] for c in validation10["checks"]}
    record("F10", "Currency mismatch invoice vs PO", "po_currency_mismatch FAIL",
           "po_currency_mismatch" in codes10 and validation10["failed_checks"] > 0,
           f"checks={sorted(codes10)}", f"invoice={inv10['id']}")

    inv11 = create_invoice(
        api, headers, f"F11-{suffix}", vendor_id=vendor_a["id"], purchase_order_id=po_a["id"],
        subtotal="900.00", total="900.00",
        items=[{"description": "x", "quantity": "1", "unit_price": "900.00", "tax_rate": "0"}],
    ).json()
    validate(api, headers, inv11["id"])
    exc11 = exceptions_for(api, headers, inv11["id"])
    partial = next((e for e in exc11 if e["exception_type"] == "AMOUNT_MISMATCH"), None)
    record("F11", "Partial invoice against larger PO", "AMOUNT_MISMATCH flagged as partial (MEDIUM)",
           bool(partial) and partial.get("evidence", {}).get("partial_invoice") is True,
           f"severity={partial['severity'] if partial else None}", f"invoice={inv11['id']}")

    inv12 = create_invoice(
        api, headers, f"F12-{suffix}", vendor_id=vendor_a["id"],
        subtotal="300.00", tax="30.00", total="330.00",
        items=[
            {"description": "a", "quantity": "1", "unit_price": "100.00", "tax_rate": "10"},
            {"description": "b", "quantity": "1", "unit_price": "100.00", "tax_rate": "10"},
            {"description": "c", "quantity": "1", "unit_price": "100.00", "tax_rate": "10"},
        ],
    ).json()
    validation12 = validate(api, headers, inv12["id"])
    codes12 = {c["code"] for c in validation12["checks"]}
    record("F12", "Multiple invoice lines with correct decimals", "No total/line/tax arithmetic failures",
           not ({"total_mismatch", "line_sum_mismatch", "line_tax_mismatch"} & codes12),
           f"checks={sorted(codes12)}", f"invoice={inv12['id']}")

    # -------------------------------------------------------- F13..F17 docs
    text_bytes = f"Acceptance invoice {suffix}\nTotal 100.00 USD\n".encode()
    up1 = upload(api, headers, f"acceptance-{suffix}.txt", text_bytes, "text/plain")
    up2 = upload(api, headers, f"acceptance-{suffix}.txt", text_bytes, "text/plain")
    dup_body = up2.json() if up2.headers.get("content-type", "").startswith("application/json") else {}
    dup_code = (dup_body.get("error") or {}).get("code")
    dup_existing = ((dup_body.get("error") or {}).get("details") or {}).get("document_id")
    record("F13", "Duplicate document upload", "HTTP 409 duplicate_document with existing id",
           up1.status_code == 201 and up2.status_code == 409 and dup_code == "duplicate_document"
           and dup_existing == up1.json()["document"]["id"],
           f"first={up1.status_code} second={up2.status_code} code={dup_code}")

    noise = Image.new("RGB", (900, 300), "white")
    draw = ImageDraw.Draw(noise)
    for x in range(0, 900, 3):
        for y in range(0, 300, 7):
            if (x + y) % 11 == 0:
                draw.point((x, y), fill=(210, 210, 210))
    draw.text((10, 140), f"INVOICE TOTAL 1O0.0O  INVOICE DATE 2O26-13-45 {suffix}", fill=(225, 225, 225))
    buffer = io.BytesIO()
    noise.save(buffer, format="PNG")
    low = upload(api, headers, f"low-quality-{suffix}.png", buffer.getvalue(), "image/png")
    low_doc = poll_document(api, headers, low.json()["document"]["id"]) if low.status_code == 201 else {}
    confidence = low_doc.get("ocr_confidence")
    record("F14", "Low OCR confidence handling", "requires_review or OCR confidence < 0.6",
           bool(low_doc.get("requires_review")) or (confidence is not None and confidence < 0.6),
           f"status={low_doc.get('status')} confidence={confidence}")

    bad = upload(api, headers, f"malware-{suffix}.exe", b"MZ\x90\x00fake", "application/octet-stream")
    record("F15", "Invalid file format rejected", "HTTP 4xx", bad.status_code >= 400, f"status={bad.status_code}")

    corrupt = upload(
        api,
        headers,
        f"corrupt-{suffix}.pdf",
        f"%PDF-1.4\nnot a real pdf {suffix} {uuid.uuid4().hex}\n".encode(),
        "application/pdf",
    )
    corrupt_doc = poll_document(api, headers, corrupt.json()["document"]["id"]) if corrupt.status_code == 201 else {}
    record("F16", "Corrupted document fails safely", "Document status FAILED with error",
           corrupt_doc.get("status") == "FAILED" and bool(corrupt_doc.get("processing_error")),
           f"status={corrupt_doc.get('status')}")

    big = upload(api, headers, f"large-{suffix}.pdf", b"%PDF-1.4\n" + b"0" * (26 * 1024 * 1024), "application/pdf")
    record("F17", "Large file rejected", "HTTP 4xx", big.status_code >= 400, f"status={big.status_code}")

    # -------------------------------------------------------- F18/F19 hooks
    integrations = api.call("GET", "/integrations", headers=headers).json()
    inbound = next(
        (
            i
            for i in integrations
            if i["kind"] == "N8N" and i["is_enabled"] and "signing_secret" in i["credential_keys"]
        ),
        None,
    )
    if inbound:
        import hashlib
        import hmac

        secret = env_values["N8N_WEBHOOK_SECRET"]
        body = '{"event_type": "integration.ping", "data": {"source": "acceptance"}}'
        key = str(uuid.uuid4())
        signature = hmac.new(secret.encode(), body.encode(), hashlib.sha256).hexdigest()
        first = api.call(
            "POST", f"/webhooks/{inbound['id']}", content=body,
            headers={"Content-Type": "application/json", "X-Resolve-Signature": signature, "Idempotency-Key": key},
        )
        second = api.call(
            "POST", f"/webhooks/{inbound['id']}", content=body,
            headers={"Content-Type": "application/json", "X-Resolve-Signature": signature, "Idempotency-Key": key},
        )
        same = first.status_code == 202 and second.status_code == 202 and first.json().get("id") == second.json().get("id")
        record("F18", "Duplicate inbound webhook", "Same event id returned, no duplicate",
               same, f"{first.status_code}/{second.status_code}")
        invalid = api.call(
            "POST", f"/webhooks/{inbound['id']}", content=body,
            headers={"Content-Type": "application/json", "X-Resolve-Signature": "0" * 64, "Idempotency-Key": str(uuid.uuid4())},
        )
        record("F19", "Invalid webhook HMAC", "HTTP 400", invalid.status_code == 400, f"status={invalid.status_code}")
    else:
        record("F18", "Duplicate inbound webhook", "Integration available", False, "no N8N integration")
        record("F19", "Invalid webhook HMAC", "Integration available", False, "no N8N integration")

    # --------------------------------------------- F20/F21 approvals and F22
    case_self, _res_self, appr_self = make_case_with_approval(api, headers, suffix, approver_id, "authorized approval")
    denied = api.call("POST", f"/approvals/{appr_self}/approve", headers=headers, json={"comment": "self"})
    record("F22", "Self-approval by requester", "HTTP 403",
           denied.status_code == 403, f"status={denied.status_code}", f"approval={appr_self}")

    # F20: concurrent approval of a fresh request (approver is the approver).
    _case_c, res_c, appr_c = make_case_with_approval(api, headers, suffix, approver_id, "concurrent approval")

    def approve_once(comment: str) -> int:
        with httpx.Client(verify=VERIFY, timeout=60) as client:
            response = client.post(
                f"{API}/approvals/{appr_c}/approve",
                headers=approver_headers,
                json={"comment": comment, "execute_after_approval": False},
            )
            return response.status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        statuses = list(pool.map(approve_once, ["concurrent-a", "concurrent-b"]))
    successes = [s for s in statuses if s < 400]
    record("F20", "Concurrent approval of one request", "Exactly one success, no duplicate decision",
           len(successes) == 1, f"statuses={statuses}", f"approval={appr_c}")

    # F21: expired approval.
    _case_e, _res_e, appr_e = make_case_with_approval(api, headers, suffix, approver_id, "expired approval")
    sql(f"update approval_requests set expires_at = now() - interval '2 hours' where id = '{appr_e}';")
    expired = api.call("POST", f"/approvals/{appr_e}/approve", headers=approver_headers, json={"comment": "late"})
    record("F21", "Expired approval cannot be approved", "HTTP 4xx",
           expired.status_code >= 400, f"status={expired.status_code}", f"approval={appr_e}")

    # F23: unauthorized execution by viewer.
    forbidden = api.call("POST", f"/resolutions/{res_c}/execute", headers=api.headers(sessions["viewer"]))
    record("F23", "Viewer cannot execute a resolution", "HTTP 403",
           forbidden.status_code == 403, f"status={forbidden.status_code}", f"resolution={res_c}")

    # F24: cross-tenant access with the isolated fixture tenant.
    other_email = env_values.get("RESOLVE_OTHER_TENANT_EMAIL", "")
    other_password = env_values.get("RESOLVE_OTHER_TENANT_PASSWORD", "")
    if other_email and other_password:
        other = api.login(other_email, other_password, env_values.get("RESOLVE_OTHER_TENANT_ORG_SLUG", ""))
        cross = api.call("GET", f"/cases/{case_self}", headers=api.headers(other))
        record("F24", "Cross-tenant case read", "HTTP 404",
               cross.status_code == 404, f"status={cross.status_code}")
    else:
        record("F24", "Cross-tenant case read", "Fixture configured", False, "no tenant fixture")

    # F25: retry after processing failure (reprocess the corrupted document).
    if corrupt_doc.get("id"):
        retry = api.call("POST", f"/documents/{corrupt_doc['id']}/reprocess", headers=headers, json={"reason": "acceptance retry"})
        after = poll_document(api, headers, corrupt_doc["id"], timeout=90) if retry.status_code == 200 else {}
        record("F25", "Retry after processing failure", "Reprocess accepted and status re-evaluated",
               retry.status_code == 200 and after.get("status") in {"FAILED", "INDEXED", "REQUIRES_REVIEW", "EXTRACTED"},
               f"reprocess={retry.status_code} final={after.get('status')}")

    # ------------------------------------------------------------- roles
    role_checks = []
    if "viewer" in sessions:
        viewer_read = api.call("GET", "/cases", headers=api.headers(sessions["viewer"]))
        viewer_write = api.call("POST", "/vendors", headers=api.headers(sessions["viewer"]),
                                json={"vendor_number": f"NO-{suffix}", "legal_name": "Denied"})
        role_checks.append(("viewer read/write", viewer_read.status_code == 200 and viewer_write.status_code == 403))
    if "investigator" in sessions:
        inv_case = api.call("POST", "/cases", headers=api.headers(sessions["investigator"]),
                            json={"title": f"Acceptance investigator case {suffix}", "priority": "LOW"})
        inv_approve = api.call("POST", f"/approvals/{appr_self}/approve",
                               headers=api.headers(sessions["investigator"]), json={"comment": "no"})
        role_checks.append(("investigator create case / no approval", inv_case.status_code == 201 and inv_approve.status_code == 403))
    if "approver" in sessions:
        allowed = api.call("POST", f"/approvals/{appr_self}/approve", headers=approver_headers,
                           json={"comment": "authorized approval"})
        role_checks.append(("approver decides approval", allowed.status_code == 200))
    if "ops_manager" in sessions:
        manager_vendor = api.call("POST", "/vendors", headers=api.headers(sessions["ops_manager"]),
                                  json={"vendor_number": f"MGR-{suffix}", "legal_name": "Manager Vendor"})
        role_checks.append(("operations manager creates vendor", manager_vendor.status_code == 201))
    if "org_admin" in sessions:
        admin_audit = api.call("GET", "/audit", headers=headers, params={"page_size": 5})
        role_checks.append(("org admin reads audit", admin_audit.status_code == 200))
    if "super_admin" in sessions:
        super_read = api.call("GET", "/cases", headers=api.headers(sessions["super_admin"]))
        role_checks.append(("super admin reads platform data", super_read.status_code == 200))
    if "automation" in sessions:
        auto_read = api.call("GET", "/analytics/overview", headers=api.headers(sessions["automation"]), params={"days": 7})
        auto_write = api.call("POST", "/vendors", headers=api.headers(sessions["automation"]),
                              json={"vendor_number": f"AUTO-{suffix}", "legal_name": "Denied"})
        role_checks.append(("automation read-only", auto_read.status_code == 200 and auto_write.status_code == 403))

    record("R01", "Role matrix (6 roles + automation account)", "All role boundaries enforced",
           all(ok for _, ok in role_checks), "; ".join(f"{name}={'ok' if ok else 'FAIL'}" for name, ok in role_checks))

    # ------------------------------------------------------------- summary
    failures = [r for r in RESULTS if r["status"] == "FAIL"]
    lines = [
        "# Final acceptance results",
        "",
        f"Run: {datetime.now(UTC).isoformat()} against `{LAN}`",
        "",
        "| ID | Scenario | Expected | Actual | Status | Evidence |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for row in RESULTS:
        lines.append(
            f"| {row['id']} | {row['scenario']} | {row['expected']} | {row['actual']} | "
            f"**{row['status']}** | `{row['evidence']}` |"
        )
    counts = Counter(r["status"] for r in RESULTS)
    lines += ["", f"**Summary:** {counts.get('PASS', 0)} PASS / {counts.get('FAIL', 0)} FAIL of {len(RESULTS)} cases."]
    Path("docs/FINAL_ACCEPTANCE_RESULTS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{counts.get('PASS', 0)}/{len(RESULTS)} passed; results written to docs/FINAL_ACCEPTANCE_RESULTS.md")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
