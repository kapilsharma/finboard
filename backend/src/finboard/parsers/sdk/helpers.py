"""Small, well-tested helpers that most adapters need: Indian-format amounts and dates."""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

_CENT = Decimal("0.01")
# Western (1,234,567) or Indian lakh (12,34,567) grouping; the last group always has 3 digits.
_AMOUNT = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d{1,2}(?:,\d{2})*,\d{3}|\d+)(?:\.\d{1,2})?$")
_CURRENCY = re.compile(r"^(?:INR|Rs\.?|₹)\s*", re.IGNORECASE)

DATE_FORMATS = (
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%d.%m.%Y",
    "%d/%m/%y",
    "%d-%m-%y",
    "%d-%b-%Y",
    "%d-%b-%y",
    "%d/%b/%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%Y-%m-%d",
)


def parse_amount(text: str) -> Decimal | None:
    """`'1,23,456.78'` → `Decimal('123456.78')`. Positive amounts only (no sign); `None` if the
    text isn't an amount. Strips a leading currency marker (INR, Rs., ₹)."""
    cleaned = _CURRENCY.sub("", text.strip()).replace(" ", "")
    if not cleaned or not _AMOUNT.match(cleaned):
        return None
    return Decimal(cleaned.replace(",", "")).quantize(_CENT, rounding=ROUND_HALF_UP)


def parse_signed_amount(text: str) -> tuple[Decimal, str | None] | None:
    """Amount with an optional trailing `Dr`/`Cr` (or leading `-`).

    Returns `(amount, marker)` where marker is "dr", "cr" or None.
    """
    cleaned = text.strip()
    marker: str | None = None
    lowered = cleaned.lower()
    for suffix in ("dr", "cr"):
        if lowered.endswith(suffix):
            marker = suffix
            cleaned = cleaned[: -len(suffix)].rstrip(" .")
            break
    if cleaned.startswith("-"):
        marker = marker or "dr"
        cleaned = cleaned[1:]
    amount = parse_amount(cleaned)
    return None if amount is None else (amount, marker)


def parse_date(text: str, formats: tuple[str, ...] = DATE_FORMATS) -> date | None:
    cleaned = text.strip()
    for fmt in formats:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def last_digits(text: str, count: int = 4) -> str | None:
    """Last `count` digits of an account/card number such as `XXXXXXXX1234` or `4111 XX 1234`."""
    digits = re.sub(r"\D", "", text)
    return digits[-count:] if len(digits) >= count else None
