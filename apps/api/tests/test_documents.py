"""Document upload, processing, extraction review and invoice creation tests."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.domain.enums import RoleCode
from tests.conftest import OrgFixture


def make_invoice_pdf(number: str = "TEST-INV-001", total: str = "1070.00") -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer)
    lines = [
        "ACME SUPPLIES LTD",
        "Tax Invoice",
        f"Invoice No: {number}",
        "Invoice Date: 2026-02-10",
        "Due Date: 2026-03-12",
        "PO Number: PO-TEST-1",
        "Tax ID: TH-001",
        "Subtotal: 1,000.00",
        "VAT 7%: 70.00",
        f"Total: {total}",
        "Currency: USD",
        "Payment Terms: Net 30",
    ]
    y = 800
    for line in lines:
        pdf.drawString(60, y, line)
        y -= 22
    pdf.save()
    return buffer.getvalue()


def upload(client: TestClient, org: OrgFixture, data: bytes, name: str = "invoice.pdf", doc_type: str = "INVOICE"):
    return client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": (name, data, "application/pdf")},
        data={"document_type": doc_type},
    )


def test_upload_process_and_extract(client: TestClient, org: OrgFixture) -> None:
    response = upload(client, org, make_invoice_pdf())
    assert response.status_code == 201, response.text
    document_id = response.json()["document"]["id"]

    detail = client.get(f"/api/v1/documents/{document_id}", headers=org.headers[RoleCode.INVESTIGATOR])
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] in {"INDEXED", "EXTRACTED", "REQUIRES_REVIEW"}
    assert body["page_count"] == 1
    assert body["char_count"] > 50
    extraction = body["extraction"]
    assert extraction is not None
    fields = {field["field_name"]: field for field in extraction["fields"]}
    assert fields["invoice_number"]["value"] == "TEST-INV-001"
    assert fields["total"]["effective_value"] == "1070.00"
    assert fields["total"]["page_number"] == 1
    assert fields["total"]["source_text"]
    assert fields["total"]["confidence"] > 0.5


def test_duplicate_upload_rejected(client: TestClient, org: OrgFixture) -> None:
    pdf = make_invoice_pdf(number="DUP-001")
    first = upload(client, org, pdf)
    assert first.status_code == 201
    second = upload(client, org, pdf, name="again.pdf")
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "duplicate_document"


def test_unsupported_file_type(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("payload.exe", b"MZ\x90\x00data", "application/x-msdownload")},
        data={"document_type": "OTHER"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unsupported_file_type"


def test_mime_mismatch_rejected(client: TestClient, org: OrgFixture) -> None:
    response = client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("fake.pdf", b"not a real pdf", "application/pdf")},
        data={"document_type": "INVOICE"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "mime_mismatch"


def test_field_correction_and_review(client: TestClient, org: OrgFixture) -> None:
    response = upload(client, org, make_invoice_pdf(number="COR-001"))
    document_id = response.json()["document"]["id"]
    detail = client.get(f"/api/v1/documents/{document_id}", headers=org.headers[RoleCode.INVESTIGATOR]).json()
    field = next(f for f in detail["extraction"]["fields"] if f["field_name"] == "total")

    corrected = client.patch(
        f"/api/v1/documents/{document_id}/fields/{field['id']}",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={"value": "999.00", "notes": "Corrected against the vendor statement"},
    )
    assert corrected.status_code == 200
    assert corrected.json()["corrected_value"] == "999.00"
    assert corrected.json()["review_status"] == "CORRECTED"

    reviewed = client.post(
        f"/api/v1/documents/{document_id}/review",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={"action": "APPROVE", "approve_low_confidence_fields": True},
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["review_status"] == "APPROVED"


def test_reject_requires_note(client: TestClient, org: OrgFixture) -> None:
    response = upload(client, org, make_invoice_pdf(number="REJ-001"))
    document_id = response.json()["document"]["id"]
    rejected = client.post(
        f"/api/v1/documents/{document_id}/review",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={"action": "REJECT"},
    )
    assert rejected.status_code == 400
    assert rejected.json()["error"]["code"] == "note_required"

    ok = client.post(
        f"/api/v1/documents/{document_id}/review",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={"action": "REJECT", "note": "Wrong vendor document"},
    )
    assert ok.status_code == 200
    assert ok.json()["review_status"] == "REJECTED"


def test_document_download_requires_auth_and_is_audited(client: TestClient, org: OrgFixture) -> None:
    response = upload(client, org, make_invoice_pdf(number="DL-001"))
    document_id = response.json()["document"]["id"]
    assert client.get(f"/api/v1/documents/{document_id}/download").status_code == 401
    download = client.get(
        f"/api/v1/documents/{document_id}/download", headers=org.headers[RoleCode.VIEWER]
    )
    assert download.status_code == 200
    assert download.content.startswith(b"%PDF")
    audit = client.get("/api/v1/audit", headers=org.headers[RoleCode.ORG_ADMIN], params={"action": "document.downloaded"})
    assert audit.status_code == 200
    assert audit.json()["meta"]["total"] >= 1


def test_create_invoice_from_document(client: TestClient, org: OrgFixture, db) -> None:
    vendor = client.post(
        "/api/v1/vendors",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "vendor_number": "V-ACME",
            "legal_name": "ACME SUPPLIES LTD",
            "tax_id": "TH-001",
            "currency": "USD",
            "email": "ap@acme.example.com",
        },
    )
    assert vendor.status_code == 201, vendor.text
    response = upload(client, org, make_invoice_pdf(number="CONV-001", total="1070.00"))
    document_id = response.json()["document"]["id"]

    created = client.post(
        f"/api/v1/documents/{document_id}/create-invoice",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={},
    )
    assert created.status_code == 200, created.text
    invoice_id = created.json()["invoice_id"]
    invoice = client.get(f"/api/v1/invoices/{invoice_id}", headers=org.headers[RoleCode.INVESTIGATOR])
    assert invoice.status_code == 200
    body = invoice.json()
    assert body["vendor"]["legal_name"] == "ACME SUPPLIES LTD"
    assert body["total"] == "1070.0000"
    assert body["source"] == "DOCUMENT"

    again = client.post(
        f"/api/v1/documents/{document_id}/create-invoice",
        headers=org.headers[RoleCode.INVESTIGATOR],
        json={},
    )
    assert again.json()["invoice_id"] == invoice_id


def test_document_versioning(client: TestClient, org: OrgFixture) -> None:
    response = upload(client, org, make_invoice_pdf(number="VER-001"))
    document_id = response.json()["document"]["id"]
    new_version = client.post(
        f"/api/v1/documents/{document_id}/versions",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("invoice-v2.pdf", make_invoice_pdf(number="VER-002"), "application/pdf")},
        data={"note": "Vendor reissued the invoice"},
    )
    assert new_version.status_code == 201, new_version.text
    assert new_version.json()["version"] == 2
    detail = client.get(f"/api/v1/documents/{document_id}", headers=org.headers[RoleCode.INVESTIGATOR]).json()
    assert detail["current_version"] == 2
    assert [version["version"] for version in detail["versions"]] == [2, 1]


def test_non_invoice_documents_are_indexed_not_invoice_parsed(client: TestClient, org: OrgFixture) -> None:
    response = upload(client, org, make_invoice_pdf(number="CONTRACT-1"), name="contract.pdf", doc_type="CONTRACT")
    assert response.status_code == 201, response.text
    document_id = response.json()["document"]["id"]
    detail = client.get(f"/api/v1/documents/{document_id}", headers=org.headers[RoleCode.INVESTIGATOR]).json()
    assert detail["document_type"] == "CONTRACT"
    assert detail["extraction"] is None
    assert detail["status"] == "INDEXED"
    assert detail["chunk_count"] >= 1


def test_knowledge_search_returns_indexed_chunks(client: TestClient, org: OrgFixture) -> None:
    upload(client, org, make_invoice_pdf(number="SEARCH-001"))
    search = client.get(
        "/api/v1/documents/search/knowledge",
        headers=org.headers[RoleCode.INVESTIGATOR],
        params={"q": "ACME SUPPLIES invoice"},
    )
    assert search.status_code == 200, search.text
    body = search.json()
    assert body["retrieval_mode"] in {"keyword", "hybrid"}
    assert body["hits"]
    assert body["hits"][0]["document_title"]

    # The optional pgvector probe must not leave the session in an aborted
    # transaction when the extension is absent (PostgreSQL only).
    follow_up = client.post(
        "/api/v1/vendors",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={"vendor_number": "AFTER-SEARCH-1", "legal_name": "After Search Ltd."},
    )
    assert follow_up.status_code == 201, follow_up.text


def test_unsupported_image_without_ocr_fails_honestly(client: TestClient, org: OrgFixture) -> None:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (200, 80), "white").save(buffer, format="PNG")
    response = client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("scan.png", buffer.getvalue(), "image/png")},
        data={"document_type": "INVOICE"},
    )
    assert response.status_code == 201
    document_id = response.json()["document"]["id"]
    detail = client.get(f"/api/v1/documents/{document_id}", headers=org.headers[RoleCode.INVESTIGATOR]).json()
    assert detail["status"] in {"FAILED", "REQUIRES_REVIEW", "INDEXED", "EXTRACTED"}
    if detail["status"] == "FAILED":
        assert "OCR" in (detail["processing_error"] or "") or "Tesseract" in (detail["processing_error"] or "")
        assert detail["requires_review"] is True

def _sample_png(text_lines: list[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    try:
        font = ImageFont.truetype("arial.ttf", 40)
    except OSError:
        font = ImageFont.load_default(size=40)
    image = Image.new("RGB", (1200, 400), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(text_lines):
        draw.text((40, 30 + index * 58), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_real_ocr_png_and_scanned_pdf(client: TestClient, org: OrgFixture) -> None:
    import pymupdf
    import pytest

    from app.modules.documents import processing

    available, _reason = processing.ocr_status()
    if not available:
        pytest.skip("Tesseract is not installed in this environment")

    png = _sample_png(["ACME SUPPLIES LTD.", "INVOICE INV-2026-9001", "Total: 1,284.00 USD"])

    response = client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("scan.png", png, "image/png")},
        data={"document_type": "INVOICE"},
    )
    assert response.status_code == 201, response.text
    detail = client.get(
        f"/api/v1/documents/{response.json()['document']['id']}",
        headers=org.headers[RoleCode.INVESTIGATOR],
    ).json()
    assert detail["status"] not in {"FAILED", "UPLOADED"}, detail.get("processing_error")
    assert detail["pages"]
    page = detail["pages"][0]
    assert "INV-2026-9001" in page["text"]
    assert page["ocr_confidence"] and page["ocr_confidence"] > 0.5
    assert page["extra"]["ocr_language"]

    pdf = pymupdf.open()
    pdf_page = pdf.new_page(width=595, height=842)
    pdf_page.insert_image(pymupdf.Rect(30, 30, 565, 400), stream=png)
    scanned = pdf.tobytes()
    pdf.close()

    response = client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("scanned.pdf", scanned, "application/pdf")},
        data={"document_type": "INVOICE"},
    )
    assert response.status_code == 201, response.text
    detail = client.get(
        f"/api/v1/documents/{response.json()['document']['id']}",
        headers=org.headers[RoleCode.INVESTIGATOR],
    ).json()
    assert detail["status"] not in {"FAILED", "UPLOADED"}, detail.get("processing_error")
    assert "INV-2026-9001" in detail["pages"][0]["text"]
    assert detail["pages"][0]["has_text_layer"] is False


def test_docx_xlsx_and_csv_are_extracted(client: TestClient, org: OrgFixture) -> None:
    import docx
    from openpyxl import Workbook

    document = docx.Document()
    document.add_heading("Purchase order PO-7788", level=1)
    document.add_paragraph("Vendor: Acme Supplies Ltd.")
    buffer = io.BytesIO()
    document.save(buffer)

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Invoice", "Total"])
    sheet.append(["INV-2026-9002", 420.5])
    xlsx = io.BytesIO()
    workbook.save(xlsx)

    cases = [
        (
            "order.docx",
            buffer.getvalue(),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "PO-7788",
        ),
        (
            "ledger.xlsx",
            xlsx.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "INV-2026-9002",
        ),
        ("items.csv", b"Invoice,Total\nINV-2026-9003,99.00\n", "text/csv", "INV-2026-9003"),
    ]
    for name, data, mime, expected in cases:
        response = client.post(
            "/api/v1/documents",
            headers=org.headers[RoleCode.INVESTIGATOR],
            files={"file": (name, data, mime)},
            data={"document_type": "OTHER"},
        )
        assert response.status_code == 201, response.text
        detail = client.get(
            f"/api/v1/documents/{response.json()['document']['id']}",
            headers=org.headers[RoleCode.INVESTIGATOR],
        ).json()
        assert detail["status"] not in {"FAILED", "UPLOADED"}, detail.get("processing_error")
        assert expected in (detail["pages"][0]["text"] if detail["pages"] else "")


def test_document_detail_text_is_bounded(client: TestClient, org: OrgFixture, db) -> None:
    from app.config.settings import settings
    from app.domain.enums import DocumentStatus, DocumentType
    from app.models.documents import Document, DocumentPage

    document = Document(
        org_id=org.org.id,
        original_filename="huge.txt",
        storage_filename="huge.txt",
        document_type=DocumentType.OTHER,
        mime_type="text/plain",
        size_bytes=1,
        sha256="0" * 64,
        storage_key="test/huge.txt",
        status=DocumentStatus.INDEXED,
    )
    db.add(document)
    db.flush()
    db.add(
        DocumentPage(
            document_id=document.id,
            page_number=1,
            text="x" * (settings.DOCUMENT_DETAIL_MAX_CHARS + 5000),
            char_count=settings.DOCUMENT_DETAIL_MAX_CHARS + 5000,
        )
    )
    db.commit()

    body = client.get(
        f"/api/v1/documents/{document.id}", headers=org.headers[RoleCode.VIEWER]
    ).json()
    assert len(body["pages"][0]["text"]) == settings.DOCUMENT_DETAIL_MAX_CHARS

def test_upload_size_limit_is_configurable(client: TestClient, org: OrgFixture, monkeypatch) -> None:
    from app.config.settings import settings

    monkeypatch.setattr(settings, "MAX_UPLOAD_MB", 1)
    payload = b"%PDF-1.4 " + b"0" * (1024 * 1024 + 10)
    response = client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("large.pdf", payload, "application/pdf")},
        data={"document_type": "INVOICE"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "file_too_large"


def test_archive_bomb_guard(monkeypatch) -> None:
    import zipfile

    import pytest

    from app.config.settings import settings
    from app.modules.documents import processing

    monkeypatch.setattr(settings, "MAX_DECOMPRESSED_MB", 1)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.bin", b"0" * (2 * 1024 * 1024))
    with pytest.raises(processing.DocumentProcessingError) as excinfo:
        processing._assert_zip_safe(buffer.getvalue(), label="DOCX")
    assert excinfo.value.code == "archive_too_large"


def test_invoice_document_link_is_validated(client: TestClient, org: OrgFixture, db) -> None:
    import uuid

    orphan = client.post(
        "/api/v1/invoices",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "invoice_number": f"ORPHAN-{uuid.uuid4().hex[:6]}",
            "invoice_date": "2026-03-01",
            "document_id": str(uuid.uuid4()),
        },
    )
    assert orphan.status_code == 400
    assert orphan.json()["error"]["code"] == "document_not_found"

    other = client.post(
        "/api/v1/documents",
        headers=org.headers[RoleCode.INVESTIGATOR],
        files={"file": ("notes.txt", b"Internal memo, not an invoice.", "text/plain")},
        data={"document_type": "OTHER"},
    )
    assert other.status_code == 201
    wrong_type = client.post(
        "/api/v1/invoices",
        headers=org.headers[RoleCode.ORG_ADMIN],
        json={
            "invoice_number": f"WRONG-{uuid.uuid4().hex[:6]}",
            "invoice_date": "2026-03-01",
            "document_id": other.json()["document"]["id"],
        },
    )
    assert wrong_type.status_code == 400
    assert wrong_type.json()["error"]["code"] == "invalid_document_type"
