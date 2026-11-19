"""Text normalization and deterministic similarity helpers."""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_WHITESPACE = re.compile(r"\s+")
_NON_ALNUM = re.compile(r"[^a-z0-9ก-๙ ]+")
_INVOICE_JUNK = re.compile(
    r"(?i)(?:\btax\s+invoice\b|\binvoice\b)\s*(?:no\.?|number|#)?[\s.:#-]*|"
    r"(?:เลขที่)?(?:ใบแจ้งหนี้|ใบกำกับภาษี)[\s.:#-]*"
)

LEGAL_SUFFIXES = {
    "co",
    "company",
    "corp",
    "corporation",
    "inc",
    "incorporated",
    "ltd",
    "limited",
    "llc",
    "plc",
    "gmbh",
    "ag",
    "sa",
    "bv",
    "pte",
    "pte ltd",
    "jsc",
    "oy",
    "ab",
    "as",
    "pcl",
    "จำกัด",
    "บริษัท",
    "มหาชน",
}


def strip_accents(value: str) -> str:
    # Thai combining marks are meaningful; only strip Latin-style diacritics.
    if any(ord(character) > 127 for character in value):
        return unicodedata.normalize("NFC", value)
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def normalize_whitespace(value: str) -> str:
    return _WHITESPACE.sub(" ", value).strip()


def normalize_name(value: str) -> str:
    """Normalize a legal entity name for matching.

    Lowercases, strips accents/punctuation, removes common legal suffixes and
    collapses whitespace. Deterministic and free of fuzzy behaviour.
    """
    text = strip_accents(value).lower()
    text = text.replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    text = normalize_whitespace(text)
    for _ in range(5):
        stripped = False
        for suffix in sorted(LEGAL_SUFFIXES, key=len, reverse=True):
            suffix_norm = normalize_whitespace(suffix)
            if text.endswith(" " + suffix_norm):
                text = text[: -len(suffix_norm) - 1].strip()
                stripped = True
        if not stripped:
            break
    for prefix in ("บริษัท", "บจก", "บมจ", "มหาชน", "จำกัด"):
        if text.startswith(prefix + " "):
            text = text[len(prefix) + 1 :].strip()
    return text


def normalize_tax_id(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^0-9A-Za-z]", "", value).upper()
    return cleaned or None


def normalize_invoice_number(value: str) -> str:
    text = _INVOICE_JUNK.sub(" ", value)
    return re.sub(r"[^0-9A-Za-z]", "", text).upper()


def normalize_currency(value: str | None, default: str = "USD") -> str:
    if not value:
        return default
    text = value.strip().upper()
    aliases = {
        "US$": "USD",
        "$": "USD",
        "DOLLAR": "USD",
        "DOLLARS": "USD",
        "€": "EUR",
        "EURO": "EUR",
        "£": "GBP",
        "฿": "THB",
        "BAHT": "THB",
        "THB": "THB",
        "¥": "JPY",
        "YEN": "JPY",
    }
    text = aliases.get(text, text)
    if len(text) == 3 and text.isalpha():
        return text
    return default


def similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def name_similarity(a: str, b: str) -> float:
    return similarity(normalize_name(a), normalize_name(b))


def tokenize(value: str) -> list[str]:
    return [t for t in re.split(r"[^0-9a-zก-๙]+", value.lower()) if len(t) > 1]


def chunk_text(text: str, *, size: int, overlap: int) -> list[str]:
    """Split text on paragraph/sentence boundaries into overlapping chunks."""
    cleaned = normalize_whitespace(text)
    if not cleaned:
        return []
    if len(cleaned) <= size:
        return [cleaned]
    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + size, length)
        if end < length:
            window = cleaned[start:end]
            split_at = max(window.rfind("\n"), window.rfind(". "), window.rfind("; "))
            if split_at > size * 0.5:
                end = start + split_at + 1
        chunk = cleaned[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks
