"""Concurrency checks against a live API: duplicate financial records and uploads.

Run with the API on the seeded PostgreSQL demo database:

    python scripts/verify_concurrency.py --base-url http://127.0.0.1:8001
"""

from __future__ import annotations

import argparse
import io
import os
import secrets
import string
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import httpx

_SECRET_FILE = Path(__file__).resolve().parents[3] / "var" / "secrets" / "demo-credentials.txt"
PASSWORD = os.environ.get("RESOLVE_DEMO_PASSWORD", "")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8001")
    args = parser.parse_args()
    global PASSWORD
    if not PASSWORD and _SECRET_FILE.exists():
        for line in _SECRET_FILE.read_text(encoding="utf-8").splitlines():
            if line.startswith("admin@example.com="):
                PASSWORD = line.split("=", 1)[1].strip()
                break
    if not PASSWORD:
        raise SystemExit("Set RESOLVE_DEMO_PASSWORD or create var/secrets/demo-credentials.txt")
    base = args.base_url.rstrip("/") + "/api/v1"

    suffix = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    with httpx.Client(timeout=60.0) as client:
        login = client.post(
            f"{base}/auth/login",
            json={"email": "admin@example.com", "password": PASSWORD, "organization_slug": "northwind"},
        )
        login.raise_for_status()
        body = login.json()
        headers = {
            "Authorization": f"Bearer {body['access_token']}",
            "X-Organization-Id": body["organization"]["id"],
        }
        vendor = client.post(
            f"{base}/vendors",
            headers=headers,
            json={
                "vendor_number": f"CONC-V-{suffix}",
                "legal_name": f"Concurrency Vendor {suffix}",
                "currency": "USD",
            },
        )
        vendor.raise_for_status()
        vendor_id = vendor.json()["id"]

        invoice_number = f"CONC-INV-{suffix}"

        def create_invoice(_index: int) -> int:
            with httpx.Client(timeout=60.0) as worker:
                response = worker.post(
                    f"{base}/invoices",
                    headers=headers,
                    json={
                        "invoice_number": invoice_number,
                        "vendor_id": vendor_id,
                        "invoice_date": date.today().isoformat(),
                        "currency": "USD",
                        "subtotal": "100.00",
                        "tax": "7.00",
                        "total": "107.00",
                    },
                )
                return response.status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            invoice_statuses = Counter(pool.map(create_invoice, range(5)))
        print(f"concurrent invoice creation statuses: {dict(invoice_statuses)}")

        pdf = _pdf(invoice_number)
        filename = f"concurrent-{suffix}.pdf"

        def upload(_index: int) -> int:
            with httpx.Client(timeout=60.0) as worker:
                response = worker.post(
                    f"{base}/documents",
                    headers=headers,
                    files={"file": (filename, pdf, "application/pdf")},
                    data={"document_type": "INVOICE"},
                )
                return response.status_code

        with ThreadPoolExecutor(max_workers=5) as pool:
            upload_statuses = Counter(pool.map(upload, range(5)))
        print(f"concurrent duplicate upload statuses: {dict(upload_statuses)}")

        invoices = client.get(
            f"{base}/invoices", headers=headers, params={"search": invoice_number, "page_size": 100}
        ).json()
        print(f"invoice rows with the shared number: {invoices['meta']['total']}")

        duplicate_flags = 0
        if invoices["items"]:
            target = invoices["items"][0]["id"]
            client.post(
                f"{base}/exceptions/scan",
                headers=headers,
                json={"invoice_id": target, "create_cases": False},
            )
            exceptions = client.get(
                f"{base}/exceptions",
                headers=headers,
                params={"entity_type": "INVOICE", "entity_id": target, "page_size": 100},
            ).json()
            duplicate_flags = sum(
                1 for item in exceptions["items"] if item["exception_type"] == "DUPLICATE_INVOICE"
            )
        print(f"DUPLICATE_INVOICE exceptions on one duplicate: {duplicate_flags}")
        documents = client.get(
            f"{base}/documents", headers=headers, params={"search": filename, "page_size": 100}
        ).json()
        print(f"document rows for the shared upload: {documents['meta']['total']}")

        ok = True
        # Duplicate invoice numbers are intentionally allowed so the duplicate
        # detection rule can investigate them; every request must still succeed
        # without leaking a server error, and one upload must deduplicate.
        if invoice_statuses.get(201, 0) != 5:
            print("FAIL: expected every concurrent invoice request to succeed")
            ok = False
        if any(status >= 500 for status in list(invoice_statuses) + list(upload_statuses)):
            print("FAIL: concurrent conflict leaked a server error")
            ok = False
        if invoices["meta"]["total"] != invoice_statuses.get(201, 0):
            print("FAIL: invoice rows do not match successful requests")
            ok = False
        if documents["meta"]["total"] != 1 or upload_statuses.get(201, 0) != 1:
            print("FAIL: duplicate documents were created")
            ok = False
        if invoices["meta"]["total"] > 1 and duplicate_flags < 1:
            print("FAIL: duplicate invoices were not surfaced by the rule engine")
            ok = False
        print("CONCURRENCY CHECKS PASSED" if ok else "CONCURRENCY CHECKS FAILED")
        return 0 if ok else 1


def _pdf(number: str) -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    pdf.drawString(60, 800, "Concurrency Test Invoice")
    pdf.drawString(60, 780, f"Invoice No: {number}")
    pdf.drawString(60, 760, "Total: 107.00")
    pdf.save()
    return buffer.getvalue()


if __name__ == "__main__":
    raise SystemExit(main())
