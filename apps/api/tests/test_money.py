"""Deterministic financial calculation tests."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.money import (
    money,
    parse_amount,
    percent_difference,
    tax_from_subtotal,
    within_tolerance,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,234.56", "1234.56"),
        ("1 234,56", "1234.56"),
        ("THB 2,500.00", "2500.00"),
        ("(123.45)", "-123.45"),
        ("1,000", "1000.00"),
        ("70.5", "70.50"),
        ("no amount", None),
        (None, None),
    ],
)
def test_parse_amount(text: str | None, expected: str | None) -> None:
    result = parse_amount(text)
    assert (None if result is None else str(result)) == expected


def test_money_rounds_commercially() -> None:
    assert money("10.005") == Decimal("10.01")
    assert money(Decimal("2.345")) == Decimal("2.35")
    assert money(3) == Decimal("3.00")


def test_tax_and_totals_use_decimal() -> None:
    tax = tax_from_subtotal(Decimal("1000.00"), Decimal("7"))
    assert tax == Decimal("70.00")
    assert tax_from_subtotal(Decimal("999.99"), Decimal("7")) == Decimal("70.00")


def test_tolerance_absolute_or_percent() -> None:
    assert within_tolerance(Decimal("1000.50"), Decimal("1000.00"), absolute=Decimal("1"), percent=Decimal("0"))
    assert within_tolerance(Decimal("1010.00"), Decimal("1000.00"), absolute=Decimal("0"), percent=Decimal("1"))
    assert not within_tolerance(Decimal("1010.01"), Decimal("1000.00"), absolute=Decimal("0"), percent=Decimal("1"))
    assert not within_tolerance(Decimal("1"), Decimal("0"), absolute=Decimal("0.50"), percent=Decimal("5"))


def test_percent_difference_zero_expected() -> None:
    assert percent_difference(Decimal("10"), Decimal("0")) == Decimal("100")
    assert percent_difference(Decimal("0"), Decimal("0")) == Decimal("0")
    assert percent_difference(Decimal("110"), Decimal("100")) == Decimal("10")
