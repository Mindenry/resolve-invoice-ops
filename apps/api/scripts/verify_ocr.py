"""Manual OCR / document-extraction verification script.

Generates real sample files (PNG, JPG, scanned PDF, text PDF, DOCX, XLSX, CSV),
runs the production parser against them and prints observed results.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.modules.documents import processing  # noqa: E402

OUT = Path(__file__).resolve().parents[3] / "var" / "ocr-samples"
OUT.mkdir(parents=True, exist_ok=True)

LINES = [
    "ACME SUPPLIES LTD.",
    "INVOICE INV-2026-0042",
    "Invoice date: 2026-03-14",
    "PO number: PO-1007",
    "Subtotal: 1,200.00 USD",
    "Tax: 84.00 USD",
    "Total: 1,284.00 USD",
]


def render_sample(path: Path, ext: str) -> bytes:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
    image = Image.new("RGB", (1400, 520), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(LINES):
        draw.text((60, 40 + index * 62), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG" if ext == "png" else "JPEG", quality=92)
    data = buffer.getvalue()
    path.write_bytes(data)
    return data


def scanned_pdf(png: bytes) -> bytes:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(30, 30, 565, 400), stream=png)
    data = document.tobytes()
    document.close()
    return data


def text_pdf() -> bytes:
    import pymupdf

    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), "INVOICE INV-2026-0043", fontsize=18)
    page.insert_text((72, 130), "Total: 999.00 USD", fontsize=14)
    data = document.tobytes()
    document.close()
    return data


def docx_bytes() -> bytes:
    import docx

    document = docx.Document()
    document.add_heading("Purchase order PO-1007", level=1)
    document.add_paragraph("Vendor: Acme Supplies Ltd.")
    document.add_paragraph("Total: 1500.00 USD")
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Invoice", "Vendor", "Total"])
    sheet.append(["INV-2026-0044", "Acme Supplies Ltd.", 420.5])
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def main() -> int:
    available, reason = processing.ocr_status()
    print(f"ocr_status={available} reason={reason}")
    print(f"ocr_languages={processing.ocr_languages()}")
    if not available:
        return 1

    failures: list[str] = []

    for ext, mime in (("png", "image/png"), ("jpg", "image/jpeg")):
        data = render_sample(OUT / f"invoice.{ext}", ext)
        parsed = processing.parse_document(data, mime_type=mime, filename=f"invoice.{ext}")
        text = parsed.full_text
        print(f"[{ext}] parser={parsed.parser} pages={len(parsed.pages)} chars={parsed.char_count} "
              f"confidence={parsed.ocr_confidence}")
        print(text[:220].replace("\n", " | "))
        if "INV-2026-0042" not in text.replace(" ", "") and "INV" not in text:
            failures.append(f"{ext}: invoice number not recognised")

    png = (OUT / "invoice.png").read_bytes()
    scanned = scanned_pdf(png)
    (OUT / "scanned.pdf").write_bytes(scanned)
    parsed = processing.parse_document(scanned, mime_type="application/pdf", filename="scanned.pdf")
    print(f"[scanned-pdf] pages={len(parsed.pages)} chars={parsed.char_count} "
          f"confidence={parsed.ocr_confidence} has_text_layer={parsed.pages[0].has_text_layer}")
    if not parsed.pages[0].text.strip():
        failures.append("scanned pdf: OCR produced no text")
    if parsed.pages[0].has_text_layer:
        failures.append("scanned pdf: expected has_text_layer=False")

    textual = text_pdf()
    (OUT / "text.pdf").write_bytes(textual)
    parsed = processing.parse_document(textual, mime_type="application/pdf", filename="text.pdf")
    print(f"[text-pdf] chars={parsed.char_count} has_text_layer={parsed.pages[0].has_text_layer}")
    if "INV-2026-0043" not in parsed.full_text:
        failures.append("text pdf: embedded text not extracted")

    formats = {
        "docx": (docx_bytes(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "PO-1007"),
        "xlsx": (xlsx_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "INV-2026-0044"),
        "csv": (b"Invoice,Vendor,Total\nINV-2026-0045,Acme,120.00\n", "text/csv", "INV-2026-0045"),
    }
    for ext, (data, mime, expected) in formats.items():
        (OUT / f"sample.{ext}").write_bytes(data)
        parsed = processing.parse_document(data, mime_type=mime, filename=f"sample.{ext}")
        print(f"[{ext}] parser={parsed.parser} chars={parsed.char_count}")
        if expected not in parsed.full_text:
            failures.append(f"{ext}: expected token {expected!r} missing")

    if failures:
        print("FAILURES:")
        for failure in failures:
            print(f" - {failure}")
        return 1
    print("ALL DOCUMENT FORMAT CHECKS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
