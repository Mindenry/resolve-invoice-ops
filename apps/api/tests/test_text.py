"""Text normalization and chunking tests."""

from __future__ import annotations

from app.core.text import (
    chunk_text,
    name_similarity,
    normalize_currency,
    normalize_invoice_number,
    normalize_name,
    normalize_tax_id,
)


def test_vendor_name_normalization_removes_legal_suffixes() -> None:
    assert normalize_name("ACME Supplies Co., Ltd.") == "acme supplies"
    assert normalize_name("Acme Supply  Limited") == "acme supply"
    assert normalize_name("บริษัท สยาม จำกัด") == "สยาม"


def test_company_suffix_does_not_break_matching() -> None:
    assert name_similarity("Mekong Trading Co., Ltd.", "Mekong Trading Company Limited") > 0.9


def test_invoice_number_normalization() -> None:
    assert normalize_invoice_number("Invoice No: INV-2026/001") == "INV2026001"
    assert normalize_invoice_number("inv 2026 001") == "INV2026001"


def test_tax_id_normalization() -> None:
    assert normalize_tax_id("TH-0105 55-0001") == "TH0105550001"
    assert normalize_tax_id(None) is None
    assert normalize_tax_id("---") is None


def test_currency_aliases() -> None:
    assert normalize_currency("฿") == "THB"
    assert normalize_currency("us$") == "USD"
    assert normalize_currency("dollars") == "USD"
    assert normalize_currency("XYZ") == "XYZ"
    assert normalize_currency("not-a-currency") == "USD"


def test_chunking_produces_overlap_and_bounds() -> None:
    text = " ".join(f"Sentence number {index} about invoice processing." for index in range(60))
    chunks = chunk_text(text, size=200, overlap=40)
    assert len(chunks) > 3
    assert all(len(chunk) <= 200 for chunk in chunks)
    assert chunk_text("", size=100, overlap=10) == []
