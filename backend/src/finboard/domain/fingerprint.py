"""Transaction fingerprint for idempotent imports (ADR-0016). Frozen: changing the output of
anything here creates duplicates, so a change needs a new `FINGERPRINT_VERSION`."""

import hashlib
import re
import unicodedata
import uuid
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from finboard.domain.money import format_plain

FINGERPRINT_VERSION = 1

_WHITESPACE = re.compile(r"\s+")


def dedupe_desc(description_raw: str) -> str:
    """upper(collapse_whitespace(NFKC(text))). Reference numbers are kept on purpose."""
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", description_raw)).strip().upper()


@dataclass(frozen=True, slots=True)
class FingerprintInput:
    date: date
    direction: str  # "debit" | "credit"
    amount: Decimal
    description_raw: str
    balance_after: Decimal | None


def _identity(row: FingerprintInput) -> tuple[str, str, str, str, str]:
    return (
        row.date.isoformat(),
        row.direction,
        format_plain(row.amount),
        dedupe_desc(row.description_raw),
        "" if row.balance_after is None else format_plain(row.balance_after),
    )


def fingerprint(account_id: uuid.UUID, row: FingerprintInput, seq_in_day: int) -> str:
    parts = ("v1", str(account_id), *_identity(row), str(seq_in_day))
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def fingerprints(account_id: uuid.UUID, rows: Iterable[FingerprintInput]) -> list[str]:
    """Fingerprint every row of one statement, in order.

    `seq_in_day` is how many identical rows (same date, direction, amount, text and balance)
    came earlier in the same statement, so two genuine identical payments on one day stay
    distinct while re-importing the statement reproduces the same fingerprints.
    """
    seen: Counter[tuple[str, str, str, str, str]] = Counter()
    result: list[str] = []
    for row in rows:
        key = _identity(row)
        result.append(fingerprint(account_id, row, seen[key]))
        seen[key] += 1
    return result


def possible_duplicates(
    new: Sequence[FingerprintInput], existing: Iterable[FingerprintInput]
) -> set[int]:
    """Indexes of `new` rows that match an existing transaction on date, direction and amount
    but not on text.

    ADR-0016 known limit: a bank may render one transaction differently in two statements
    (truncation, for example), which gives it a different fingerprint. The preview flags these
    rows so the user can decide; they are not excluded automatically.
    """
    texts: dict[tuple[date, str, str], set[str]] = {}
    for row in existing:
        key = (row.date, row.direction, format_plain(row.amount))
        texts.setdefault(key, set()).add(dedupe_desc(row.description_raw))
    flagged: set[int] = set()
    for index, row in enumerate(new):
        seen = texts.get((row.date, row.direction, format_plain(row.amount)))
        if seen and dedupe_desc(row.description_raw) not in seen:
            flagged.add(index)
    return flagged
