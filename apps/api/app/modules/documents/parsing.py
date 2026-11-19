"""Deterministic invoice field parsing from extracted page text.

This is the first stage of the document intelligence pipeline. It is transparent,
testable and free. The LLM fallback only runs when required fields remain missing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from app.core.money import parse_amount
from app.core.text import normalize_currency

MAX_SOURCE_TEXT = 400


@dataclass(slots=True)
class FieldCandidate:
    field_name: str
    value: str
    page_number: int
    source_text: str
    confidence: float
    method: str = "RULE"
    bounding_box: dict[str, float] | None = None


_DATE_RE = re.compile(
    r"(?P<date>\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b|\b\d{4}-\d{1,2}-\d{1,2}\b|"
    r"\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4}\b)",
    re.IGNORECASE,
)
_AMOUNT_RE = re.compile(
    r"(?<![\w.\-])(?P<amount>\(?\s*[-+]?"
    r"(?:\d{1,3}(?:[,\s]\d{3})+(?:[.,]\d{2})?|\d+(?:[.,]\d{2})?)"
    r"\s*\)?)(?![\d.,])"
)

FIELD_LABELS: dict[str, tuple[str, ...]] = {
    "invoice_number": (
        r"\binvoice\s*(?:no\.?|number|#)\b",
        r"\btax\s+invoice\s*(?:no\.?|number|#)\b",
        r"\binv\s*(?:no\.?|#)\b",
        r"เลขที่(?:ใบแจ้งหนี้|ใบกำกับภาษี)?",
    ),
    "invoice_date": (
        r"\binvoice\s*date\b",
        r"\bdate\s*of\s*issue\b",
        r"\bissue\s*date\b",
        r"วันที่(?:ออก)?(?:ใบแจ้งหนี้|ใบกำกับภาษี)?",
    ),
    "due_date": (r"\bdue\s*date\b", r"\bpayment\s*due\b", r"กำหนดชำระ"),
    "purchase_order_number": (
        r"\bp\.?\s*o\.?\s*(?:no\.?|number|#)\b",
        r"\bpurchase\s*order\s*(?:no\.?|number|#)?\b",
        r"ใบสั่งซื้อ",
    ),
    "vendor_tax_id": (
        r"\b(?:vendor|supplier)?\s*(?:tax|vat)\s*(?:id|number|no\.?)\b",
        r"\btax\s*identification\b",
        r"เลขประจำตัวผู้เสียภาษี",
    ),
    "subtotal": (r"\bsub\s*-?\s*total\b", r"\bnet\s*amount\b", r"ยอดรวมก่อนภาษี", r"รวมเป็นเงิน"),
    "tax": (r"\b(?:vat|tax)\b(?:\s*(?:amount|7%|10%))?", r"ภาษีมูลค่าเพิ่ม"),
    "total": (
        r"\b(?:grand\s*)?total\b(?:\s*(?:due|amount))?",
        r"\bamount\s*due\b",
        r"\bbalance\s*due\b",
        r"ยอดรวมทั้งสิ้น",
        r"ยอดชำระ",
    ),
    "currency": (r"\bcurrency\b", r"สกุลเงิน"),
    "payment_terms": (r"\bpayment\s*terms?\b", r"\bterms?\s*of\s*payment\b", r"เงื่อนไขการชำระเงิน"),
    "vendor_name": (r"\b(?:from|vendor|supplier|seller|bill(?:ed)?\s*from)\s*[:\-]", r"ผู้ขาย", r"ผู้ออกใบแจ้งหนี้"),
}

CURRENCY_TOKENS = {
    "USD": "USD",
    "US$": "USD",
    "THB": "THB",
    "฿": "THB",
    "BAHT": "THB",
    "EUR": "EUR",
    "€": "EUR",
    "GBP": "GBP",
    "£": "GBP",
    "JPY": "JPY",
    "¥": "JPY",
    "SGD": "SGD",
    "CNY": "CNY",
    "AUD": "AUD",
}

_THAI_MONTHS = {
    "ม.ค.": 1,
    "ก.พ.": 2,
    "มี.ค.": 3,
    "เม.ย.": 4,
    "พ.ค.": 5,
    "มิ.ย.": 6,
    "ก.ค.": 7,
    "ส.ค.": 8,
    "ก.ย.": 9,
    "ต.ค.": 10,
    "พ.ย.": 11,
    "ธ.ค.": 12,
}


def _lines(text: str) -> list[tuple[int, str]]:
    return [(index, line.strip()) for index, line in enumerate(text.splitlines()) if line.strip()]


def _label_match(line: str, labels: tuple[str, ...]) -> str | None:
    for label in labels:
        match = re.search(rf"(?:{label})\s*[:#-]?\s*(?P<value>.+)$", line, re.IGNORECASE)
        if match:
            value = match.group("value").strip(" :#-")
            if value:
                return value
    return None


def parse_date(value: str) -> date | None:
    cleaned = value.strip().replace(",", "")
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y"):
        try:
            parsed = datetime.strptime(cleaned, fmt).date()
            if parsed.year > 2400:  # Thai Buddhist calendar
                parsed = parsed.replace(year=parsed.year - 543)
            return parsed
        except ValueError:
            continue
    for thai, month in _THAI_MONTHS.items():
        pattern = rf"(\d{{1,2}})\s*{re.escape(thai)}\s*(\d{{4}}|\d{{2}})"
        match = re.search(pattern, value)
        if match:
            day = int(match.group(1))
            year = int(match.group(2))
            if year > 2400:
                year -= 543
            elif year < 100:
                year += 2000
            try:
                return date(year, month, day)
            except ValueError:
                return None
    return None


def _amount_from(line: str, labels: tuple[str, ...]) -> tuple[Decimal, str] | None:
    for label in labels:
        for match in re.finditer(label, line, re.IGNORECASE):
            amount_match = _AMOUNT_RE.search(line[match.end():])
            if amount_match:
                amount = parse_amount(amount_match.group(0))
                if amount is not None:
                    return amount, line
    return None


def _looks_like_vendor(line: str) -> bool:
    lowered = line.lower()
    if any(token in lowered for token in ("invoice", "receipt", "tax invoice", "ใบแจ้งหนี้", "ใบเสร็จ")):
        return False
    if ":" in line:
        return False
    if len(line) < 3 or len(line) > 120:
        return False
    return bool(re.search(r"[A-Za-zก-๙]", line))


def extract_invoice_fields(
    pages: list[tuple[int, str]], *, ocr_confidence: float | None = None
) -> list[FieldCandidate]:
    candidates: list[FieldCandidate] = []
    found: set[str] = set()

    def add(field_name: str, value: str, page: int, source: str, confidence: float) -> None:
        if field_name in found or not value:
            return
        found.add(field_name)
        adjusted = confidence
        if ocr_confidence is not None:
            adjusted = round(min(confidence, max(0.25, confidence * (0.5 + ocr_confidence / 2))), 3)
        candidates.append(
            FieldCandidate(
                field_name=field_name,
                value=value[:500],
                page_number=page,
                source_text=source.strip()[:MAX_SOURCE_TEXT],
                confidence=round(adjusted, 3),
            )
        )

    for page_number, line in [(page, line) for page, text in pages for _, line in _lines(text)]:
        for field_name in ("invoice_number", "purchase_order_number", "vendor_tax_id", "currency", "payment_terms"):
            if field_name in found:
                continue
            value = _label_match(line, FIELD_LABELS[field_name])
            if value:
                if field_name == "invoice_number":
                    value = value.split()[0].strip(".,;")
                if field_name == "purchase_order_number":
                    value = value.split()[0].strip(".,;")
                if field_name == "vendor_tax_id":
                    value = re.sub(r"[^0-9A-Za-z\-]", "", value)[:32]
                if field_name == "currency":
                    token = value.split()[0].upper().strip(".,;")
                    value = CURRENCY_TOKENS.get(token, normalize_currency(token, default=""))
                    if not value:
                        continue
                add(field_name, value, page_number, line, 0.92)

        for field_name in ("invoice_date", "due_date"):
            if field_name in found:
                continue
            value = _label_match(line, FIELD_LABELS[field_name])
            if value:
                parsed = parse_date(value)
                if parsed:
                    add(field_name, parsed.isoformat(), page_number, line, 0.93)
                    continue
            if field_name == "invoice_date" and re.search(r"(?i)invoice", line):
                match = _DATE_RE.search(line)
                if match:
                    parsed = parse_date(match.group("date"))
                    if parsed:
                        add(field_name, parsed.isoformat(), page_number, line, 0.72)

        for field_name in ("subtotal", "tax", "total"):
            if field_name in found:
                continue
            if field_name == "tax" and re.search(r"(?i)\b(?:tax|vat)\s*(?:id|number|no\.?)\b", line):
                continue
            result = _amount_from(line, FIELD_LABELS[field_name])
            if result:
                amount, source = result
                add(field_name, str(amount), page_number, source, 0.9)

        if "vendor_name" not in found:
            value = _label_match(line, FIELD_LABELS["vendor_name"])
            if value:
                add("vendor_name", value.strip(), page_number, line, 0.85)

        if "currency" not in found:
            for token, code in CURRENCY_TOKENS.items():
                if token in line:
                    add("currency", code, page_number, line, 0.6)
                    break

    if "vendor_name" not in found:
        for page, text in pages:
            for _, line in _lines(text)[:12]:
                if _looks_like_vendor(line):
                    add("vendor_name", line.strip(), page, line, 0.72)
                    break
            if "vendor_name" in found:
                break

    if "total" not in found:
        for page, text in pages:
            amounts = [parse_amount(match.group(0)) for match in _AMOUNT_RE.finditer(text)]
            amounts = [amount for amount in amounts if amount is not None and amount > 0]
            if amounts:
                largest = max(amounts)
                source_line = next(
                    (line for _, line in _lines(text) if str(largest) in line.replace(",", "")),
                    f"Largest amount detected: {largest}",
                )
                add("total", str(largest), page, source_line, 0.45)

    if "subtotal" in found and "tax" in found and "total" not in found:
        subtotal = next(Decimal(c.value) for c in candidates if c.field_name == "subtotal")
        tax = next(Decimal(c.value) for c in candidates if c.field_name == "tax")
        page = next(c.page_number for c in candidates if c.field_name == "subtotal")
        add("total", str((subtotal + tax).quantize(Decimal("0.01"))), page, "Derived: subtotal + tax", 0.7)
        candidates[-1].method = "DERIVED"

    return candidates


REQUIRED_FIELDS = ("invoice_number", "invoice_date", "total")
OPTIONAL_FIELDS = (
    "due_date",
    "vendor_name",
    "vendor_tax_id",
    "purchase_order_number",
    "currency",
    "subtotal",
    "tax",
    "payment_terms",
)


def missing_required(candidates: list[FieldCandidate]) -> list[str]:
    present = {candidate.field_name for candidate in candidates if candidate.value}
    return [field for field in REQUIRED_FIELDS if field not in present]


def average_confidence(candidates: list[FieldCandidate]) -> float:
    if not candidates:
        return 0.0
    return round(sum(candidate.confidence for candidate in candidates) / len(candidates), 3)
