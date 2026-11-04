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


def find_possible_duplicates(
    rows: Sequence[FingerprintInput],
) -> list[tuple[int, int]]:
    """Pairs (i, j), i < j, with the same date, direction and amount but different text.

    ADR-0016 known limit: a bank may render one transaction differently in two statements.
    The preview flags these so the user can decide.
    """
    by_key: dict[tuple[date, str, str], list[int]] = {}
    for index, row in enumerate(rows):
        by_key.setdefault((row.date, row.direction, format_plain(row.amount)), []).append(index)
    pairs: list[tuple[int, int]] = []
    for indexes in by_key.values():
        for a_pos, a in enumerate(indexes):
            for b in indexes[a_pos + 1 :]:
                if dedupe_desc(rows[a].description_raw) != dedupe_desc(rows[b].description_raw):
                    pairs.append((a, b))
    return pairs
