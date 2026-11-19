"""Generate small, obviously synthetic invoice files for manual testing."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path("var/testdata")
OUT.mkdir(parents=True, exist_ok=True)

lines = [
    ("INVOICE", 20),
    ("", 10),
    ("Vendor: Bangkok Office Supply Co., Ltd.", 11),
    ("Tax ID: TH0105551001", 11),
    ("Invoice No: INV-DEMO-1001", 11),
    ("Invoice Date: 2026-11-19", 11),
    ("Purchase Order: PO-DEMO-1001", 11),
    ("", 10),
    ("Description                Qty      Unit Price      Amount", 10),
    ("A4 paper (box)              10          120.00      1,200.00", 10),
    ("Toner cartridge              2        1,500.00      3,000.00", 10),
    ("", 8),
    ("Subtotal: 4,200.00", 11),
    ("VAT 7%: 294.00", 11),
    ("Total: 4,494.00 THB", 12),
    ("", 10),
    ("Payment terms: 30 days", 9),
    ("This file is synthetic test data.", 8),
]

pdf_path = OUT / "INV-DEMO-1001.pdf"
pdf = canvas.Canvas(str(pdf_path), pagesize=A4)
y = 780
for text, size in lines:
    if text:
        pdf.setFont("Helvetica-Bold" if size >= 12 else "Helvetica", size)
        pdf.drawString(60, y, text)
    y -= size + 10
pdf.save()

png_path = OUT / "INV-DEMO-1001.png"
image = Image.new("RGB", (1240, 1754), "white")
draw = ImageDraw.Draw(image)
try:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 28)
    title_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", 40)
except OSError:
    font = ImageFont.load_default()
    title_font = font
y = 120
for text, size in lines:
    if text:
        draw.text((100, y), text, fill="black", font=title_font if size >= 20 else font)
    y -= 45 if size >= 20 else 38
image.save(png_path)

corrupt = OUT / "corrupt-invoice.pdf"
corrupt.write_bytes(b"%PDF-1.4\nthis is not a real pdf\n%%EOF\n")

print(pdf_path)
print(png_path)
print(corrupt)
