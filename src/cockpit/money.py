"""Exact decimal helpers. Money and quantities never go through floats."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

ZERO = Decimal(0)
CENT = Decimal("0.01")
# Below this quantity a line is considered fully sold (fractional-share dust).
SHARE_EPSILON = Decimal("0.000001")


def dec(value: object) -> Decimal:
    """Parse an exported value; empty cells count as zero."""
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    text = str(value).strip()
    if not text:
        return ZERO
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"valeur numérique illisible : {text!r}") from exc


def is_decimal(value: object) -> bool:
    try:
        dec(value)
    except ValueError:
        return False
    return True


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money(value: Decimal | None) -> float | None:
    """Rounded to the cent, for JSON output only."""
    return None if value is None else float(cents(value))


def qty(value: Decimal | None) -> float | None:
    return None if value is None else float(value.quantize(Decimal("0.000001")))


def ratio(numerator: Decimal, denominator: Decimal) -> float | None:
    if denominator == 0:
        return None
    return float((numerator / denominator).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))
