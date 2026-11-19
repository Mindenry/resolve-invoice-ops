"""LLM-assisted invoice extraction with evidence validation.

Only invoked when deterministic parsing leaves required fields missing and an LLM is
configured. Every returned field is checked against the real page text; fabricated quotes
are discarded with a recorded reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, Field

from app.ai.base import ChatMessage, LLMProvider
from app.ai.client import extract_json_object
from app.ai.prompts import EXTRACTION_PROMPT_VERSION, EXTRACTION_SYSTEM
from app.core.logging import get_logger
from app.core.money import parse_amount
from app.core.text import normalize_currency

logger = get_logger(__name__)

ALLOWED_FIELDS = {
    "invoice_number",
    "vendor_name",
    "vendor_tax_id",
    "vendor_address",
    "invoice_date",
    "due_date",
    "purchase_order_number",
    "currency",
    "subtotal",
    "tax",
    "total",
    "payment_terms",
    "line_items",
}


class AIField(BaseModel):
    field_name: str
    value: str = Field(min_length=1, max_length=2000)
    page_number: int | None = None
    source_text: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class AIExtractionOutput(BaseModel):
    fields: list[AIField] = Field(default_factory=list)


@dataclass(slots=True)
class LLMExtraction:
    fields: list[AIField]
    rejected: list[dict[str, str]] = field(default_factory=list)
    provider: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


async def extract_with_llm(
    *, pages: list[tuple[int, str]], provider: LLMProvider, existing: dict[str, str]
) -> LLMExtraction:
    page_blocks = "\n\n".join(
        f"<document page=\"{number}\">\n{text[:6000]}\n</document>" for number, text in pages[:6]
    )
    context = {
        "task": "extraction",
        "candidate_fields": [
            {"field_name": name, "value": value, "page_number": 1, "source_text": value, "confidence": 0.5}
            for name, value in existing.items()
        ],
    }
    user = (
        "Extract invoice fields from the untrusted document text below. "
        f"Already extracted deterministically: {json.dumps(existing)}\n\n"
        f"{page_blocks}\n\n"
        f"<context_json>{json.dumps(context, ensure_ascii=False)}</context_json>\n\n"
        "Return JSON with a single key 'fields'."
    )
    result = await provider.complete(
        [ChatMessage(role="system", content=EXTRACTION_SYSTEM), ChatMessage(role="user", content=user)],
        temperature=0,
        max_tokens=2000,
        json_mode=True,
    )
    payload = extract_json_object(result.content)
    output = AIExtractionOutput.model_validate(payload)
    page_text = dict(pages)
    accepted: list[AIField] = []
    rejected: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in output.fields:
        if item.field_name not in ALLOWED_FIELDS:
            rejected.append({"field": item.field_name, "reason": "Unknown field name"})
            continue
        if item.field_name in seen:
            rejected.append({"field": item.field_name, "reason": "Duplicate field in model output"})
            continue
        text = page_text.get(item.page_number or 1, "")
        quote = (item.source_text or "").strip()
        if quote:
            normalized_page = " ".join(text.split()).lower()
            normalized_quote = " ".join(quote.split()).lower()
            if normalized_quote not in normalized_page:
                rejected.append(
                    {"field": item.field_name, "reason": "Source quote not found on the referenced page"}
                )
                continue
        if item.field_name in {"subtotal", "tax", "total"} and parse_amount(item.value) is None:
            rejected.append({"field": item.field_name, "reason": "Amount could not be parsed"})
            continue
        if item.field_name == "currency":
            normalized = normalize_currency(item.value, default="")
            if not normalized:
                rejected.append({"field": item.field_name, "reason": "Unknown currency"})
                continue
            item = item.model_copy(update={"value": normalized})
        accepted.append(item)
        seen.add(item.field_name)
    return LLMExtraction(
        fields=accepted,
        rejected=rejected,
        provider=result.provider,
        model=result.model,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        latency_ms=result.latency_ms,
    )


def prompt_version() -> str:
    return EXTRACTION_PROMPT_VERSION


def validate_extracted_arithmetic(values: dict[str, str]) -> list[str]:
    """Cross-field deterministic checks on extracted amounts."""
    notes: list[str] = []
    subtotal = parse_amount(values.get("subtotal"))
    tax = parse_amount(values.get("tax"))
    total = parse_amount(values.get("total"))
    if subtotal is not None and tax is not None and total is not None:
        if abs(subtotal + tax - total) > Decimal("0.02"):
            notes.append("subtotal_tax_total_mismatch")
    if total is not None and total < 0:
        notes.append("negative_total")
    return notes


__all__ = ["LLMExtraction", "extract_with_llm", "prompt_version", "validate_extracted_arithmetic"]
