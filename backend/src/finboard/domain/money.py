"""Money helpers (ADR-0008): exact `Decimal` at 2 dp. Floats are refused, never rounded."""

import re
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

CENT = Decimal("0.01")
ZERO = Decimal("0.00")
# NUMERIC(14,2): 12 digits before the point.
MAX_AMOUNT = Decimal("999999999999.99")

# Western (1,234,567) or Indian lakh (12,34,567) grouping; the last group always has 3 digits.
_AMOUNT_TEXT = re.compile(
    r"^[+-]?(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}|\d+)(?:\.\d{1,2})?$"
)


def to_money(value: Decimal | int | str) -> Decimal:
    """Quantise to 2 dp. Accepts Decimal, int or a plain decimal string; raises on float."""
    if isinstance(value, (bool, float)):
        raise TypeError("money must not be a float (or bool); use Decimal or a decimal string")
    try:
        result = Decimal(value) if not isinstance(value, Decimal) else value
    except InvalidOperation as exc:
        raise ValueError("not a decimal number") from exc
    if not result.is_finite():
        raise ValueError("money must be finite")
    quantised = result.quantize(CENT, rounding=ROUND_HALF_UP)
    if abs(quantised) > MAX_AMOUNT:
        raise ValueError("amount out of range")
    return quantised


def is_money(value: object) -> bool:
    """True for a finite Decimal that already has exactly 2 decimal places."""
    return (
        isinstance(value, Decimal)
        and value.is_finite()
        and value.as_tuple().exponent == -2
        and abs(value) <= MAX_AMOUNT
    )


def parse_amount(text: str) -> Decimal | None:
    """Parse a statement amount such as `1,23,456.78`, `1234.5` or `-50.00`.

    Indian (lakh) and Western digit grouping are both accepted. Currency markers (INR, Rs.)
    must be stripped by the caller. Returns None if the text isn't an amount.
    """
    cleaned = text.strip().replace(" ", "")
    if not cleaned or not _AMOUNT_TEXT.match(cleaned):
        return None
    return to_money(cleaned.replace(",", ""))


def format_plain(amount: Decimal) -> str:
    """`Decimal('1234.5')` → `'1234.50'` (fixed 2 dp, no grouping), as used in fingerprints."""
    return f"{to_money(amount):.2f}"
