"""Precision-safe money and percentage helpers.

Monetary values are accumulated with :class:`decimal.Decimal` so that sums of
many rows do not accumulate binary floating point drift.  Values are only
converted to ``float`` at the JSON boundary.
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

CENT = Decimal("0.01")
MILLION = Decimal("1000000")

#: Common currency symbols mapped to ISO codes.
CURRENCY_SYMBOLS: dict[str, str] = {
    "$": "USD",
    "US$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₹": "INR",
    "₽": "RUB",
    "₩": "KRW",
    "R$": "BRL",
    "C$": "CAD",
    "A$": "AUD",
}

CURRENCY_CODES = {
    "USD",
    "EUR",
    "GBP",
    "JPY",
    "CNY",
    "INR",
    "CAD",
    "AUD",
    "CHF",
    "SEK",
    "NOK",
    "DKK",
    "BRL",
    "MXN",
    "ZAR",
    "NZD",
    "SGD",
    "HKD",
    "KRW",
    "TRY",
    "PLN",
}


def to_decimal(value: Any) -> Decimal | None:
    """Best-effort conversion of ``value`` to :class:`Decimal`.

    Handles ints, floats, Decimals and numeric strings (with currency
    symbols, thousands separators, parentheses for negatives and percent
    signs).  Returns ``None`` when the value cannot be interpreted.
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return Decimal(str(value))
    if not isinstance(value, str):
        return None

    text = value.strip()
    if not text:
        return None
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1].strip()
    percent = text.endswith("%")
    if percent:
        text = text[:-1].strip()
    for symbol in CURRENCY_SYMBOLS:
        if text.startswith(symbol):
            text = text[len(symbol) :].strip()
            break
    for symbol in CURRENCY_SYMBOLS:
        if text.endswith(symbol):
            text = text[: -len(symbol)].strip()
            break
    if text.startswith("-"):
        negative = True
        text = text[1:].strip()
    elif text.startswith("+"):
        text = text[1:].strip()
    text = text.replace(",", "").replace(" ", "").replace("\u00a0", "")
    if not text or not re_is_number(text):
        return None
    try:
        result = Decimal(text)
    except InvalidOperation:
        return None
    if negative:
        result = -result
    if percent:
        result = result / Decimal(100)
    return result


def re_is_number(text: str) -> bool:
    """True when ``text`` looks like a plain decimal number."""
    if not text:
        return False
    body = text[1:] if text[0] in "+-" else text
    if not body:
        return False
    if body.count(".") > 1:
        return False
    return all(ch.isdigit() or ch == "." for ch in body)


def quantize_money(value: Any, places: int = 2) -> float:
    """Round ``value`` to ``places`` decimals using banker's-free HALF_UP."""
    dec = to_decimal(value)
    if dec is None:
        return 0.0
    exponent = Decimal(1).scaleb(-places)
    return float(dec.quantize(exponent, rounding=ROUND_HALF_UP))


def sum_money(values: Iterable[Any]) -> float:
    """Sum monetary values with Decimal precision."""
    total = Decimal(0)
    for value in values:
        dec = to_decimal(value)
        if dec is not None:
            total += dec
    return float(total)


def percent_change(new: Any, old: Any) -> tuple[float | None, str]:
    """Percentage change with explicit zero-denominator semantics.

    Returns ``(value, note)``.  ``value`` is ``None`` when the percentage is
    mathematically undefined (0 -> 0) and the note explains what happened.
    """
    new_d = to_decimal(new)
    old_d = to_decimal(old)
    if new_d is None or old_d is None:
        return None, "percentage change undefined: non-numeric operand"
    if old_d == 0:
        if new_d == 0:
            return 0.0, "both periods are zero: change defined as 0%"
        return None, "baseline period is zero: percentage change is undefined (absolute change shown instead)"
    change = (new_d - old_d) / old_d * Decimal(100)
    # Ten decimals of internal precision; the presentation layer rounds to two.
    return (
        float(change.quantize(Decimal("0.0000000001"), rounding=ROUND_HALF_UP)),
        "computed as (new - old) / old * 100",
    )


def absolute_change(new: Any, old: Any) -> float:
    new_d = to_decimal(new) or Decimal(0)
    old_d = to_decimal(old) or Decimal(0)
    return float((new_d - old_d).quantize(CENT, rounding=ROUND_HALF_UP))


def format_money(value: Any, currency: str = "USD", places: int = 2) -> str:
    """Human readable money string, e.g. ``$1,234.56``."""
    dec = to_decimal(value)
    if dec is None:
        return "-"
    quantised = dec.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    sign = "-" if quantised < 0 else ""
    body = f"{abs(quantised):,.{places}f}"
    symbol = {"USD": "$", "EUR": "€", "GBP": "£", "JPY": "¥"}.get(currency.upper(), "")
    return f"{sign}{symbol}{body}" if symbol else f"{sign}{body} {currency.upper()}"


def detect_currency(values: Iterable[Any], default: str = "USD") -> str:
    """Infer a currency code from a sample of cell values."""
    for value in values:
        if not isinstance(value, str):
            continue
        text = value.strip()
        for symbol, code in CURRENCY_SYMBOLS.items():
            if text.startswith(symbol) or text.endswith(symbol):
                return code
        upper = text.upper()
        if upper in CURRENCY_CODES:
            return upper
    return default
