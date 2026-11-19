"""Decimal money helpers.

Financial values are never represented as float inside business logic. Values enter as
Decimal, are quantized to the currency scale at the boundary, and are stored as
Numeric(18, 4). Floats only appear in analytics/ratios.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from app.core.errors import BadRequestError

CENT = Decimal("0.01")
ZERO = Decimal("0")


def to_decimal(value: object, *, field: str = "amount") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool) or value is None:
        raise BadRequestError(f"{field} must be a numeric value.", code="invalid_amount")
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise BadRequestError(f"{field} must be a numeric value.", code="invalid_amount") from exc


def money(value: object, *, field: str = "amount") -> Decimal:
    """Quantize to 2 decimal places using commercial rounding."""
    return to_decimal(value, field=field).quantize(CENT, rounding=ROUND_HALF_UP)


def safe_money(value: object, default: Decimal = ZERO) -> Decimal:
    try:
        return money(value)
    except BadRequestError:
        return default


def parse_amount(text: str | None) -> Decimal | None:
    """Parse an amount from a document: handles '1,234.56', 'THB 1 234,56', '(123.45)'."""
    if not text:
        return None
    cleaned = text.strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    cleaned = cleaned.strip("()")
    cleaned = "".join(ch for ch in cleaned if ch.isdigit() or ch in ".,-")
    if not cleaned:
        return None
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif cleaned.count(",") == 1 and "." not in cleaned:
        head, _, tail = cleaned.partition(",")
        # Treat a 3-digit tail as a thousands separator, otherwise as a decimal comma.
        cleaned = head + tail if len(tail) == 3 else head + "." + tail
    else:
        cleaned = cleaned.replace(",", "")
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None
    if negative:
        amount = -amount
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def tax_from_subtotal(subtotal: Decimal, rate_percent: Decimal) -> Decimal:
    return money(subtotal * rate_percent / Decimal("100"))


def total_with_tax(subtotal: Decimal, tax: Decimal) -> Decimal:
    return money(subtotal + tax)


def within_tolerance(actual: Decimal, expected: Decimal, *, absolute: Decimal, percent: Decimal) -> bool:
    """True when |actual - expected| is inside either tolerance (OR semantics)."""
    difference = abs(actual - expected)
    if difference <= absolute:
        return True
    if expected == ZERO:
        return False
    return difference / abs(expected) * Decimal("100") <= percent


def percent_difference(actual: Decimal, expected: Decimal) -> Decimal:
    if expected == ZERO:
        return ZERO if actual == ZERO else Decimal("100")
    return abs(actual - expected) / abs(expected) * Decimal("100")
