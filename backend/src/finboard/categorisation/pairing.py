"""Own-account transfer pairing (ARCHITECTURE §9, "Transfer pairing"). Pure.

A candidate pair is a debit in account A and a credit in a different account B for the same
amount, at most 3 days apart. Accounts of type loan, insurance or mutual_fund never take part:
their rows are already *Account movement*, so pairing them would count nothing new.

Pairs are chosen greedily and 1:1: candidates are ranked by date gap (smaller first), then by
how many transfer hints the two descriptions carry (more first), then by date and ids so the
result is deterministic. Pairs the user rejected are never suggested again.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

MAX_DAYS_APART = 3
EXCLUDED_ACCOUNT_TYPES = frozenset({"loan", "insurance", "mutual_fund"})
# Words that make a debit/credit look like money moving between the user's own accounts.
TRANSFER_HINTS = frozenset(
    {
        "TRANSFER", "TRF", "NEFT", "IMPS", "RTGS", "SELF", "OWN", "SWEEP", "CC", "CARD",
        "CREDIT", "BILL", "PAYMENT", "AUTOPAY", "AUTODEBIT", "RECEIVED", "THANK", "INFT",
    }
)  # fmt: skip


@dataclass(frozen=True, slots=True)
class PairCandidate:
    id: uuid.UUID
    account_id: uuid.UUID
    account_type: str
    date: date
    direction: str  # "debit" | "credit"
    amount: Decimal
    description_norm: str


@dataclass(frozen=True, slots=True)
class SuggestedPair:
    debit_id: uuid.UUID
    credit_id: uuid.UUID
    days_apart: int
    hints: int

    @property
    def score(self) -> float:
        """0-1, for display: same day with hints scores highest."""
        closeness = 1 - self.days_apart / (MAX_DAYS_APART + 1)
        return round(min(1.0, 0.7 * closeness + 0.1 * self.hints), 3)


def hint_count(description_norm: str) -> int:
    return len(TRANSFER_HINTS.intersection(description_norm.split()))


def suggest_pairs(
    txns: Iterable[PairCandidate],
    *,
    rejected: Iterable[tuple[uuid.UUID, uuid.UUID]] = (),
) -> list[SuggestedPair]:
    """Greedy 1:1 pairing. `txns` should exclude anything already paired or confirmed."""
    blocked = set(rejected)
    usable = [t for t in txns if t.account_type not in EXCLUDED_ACCOUNT_TYPES]
    credits_by_amount: dict[Decimal, list[PairCandidate]] = defaultdict(list)
    for txn in usable:
        if txn.direction == "credit":
            credits_by_amount[txn.amount].append(txn)

    options: list[tuple[int, int, date, uuid.UUID, uuid.UUID]] = []
    for debit in usable:
        if debit.direction != "debit":
            continue
        for credit in credits_by_amount.get(debit.amount, ()):
            if credit.account_id == debit.account_id or (debit.id, credit.id) in blocked:
                continue
            gap = abs((credit.date - debit.date).days)
            if gap > MAX_DAYS_APART:
                continue
            hints = hint_count(debit.description_norm) + hint_count(credit.description_norm)
            options.append((gap, -hints, debit.date, debit.id, credit.id))

    options.sort()
    taken: set[uuid.UUID] = set()
    pairs: list[SuggestedPair] = []
    for gap, neg_hints, _, debit_id, credit_id in options:
        if debit_id in taken or credit_id in taken:
            continue
        taken.update((debit_id, credit_id))
        pairs.append(SuggestedPair(debit_id, credit_id, gap, -neg_hints))
    return pairs


def transfer_category_key(account_types: Sequence[str]) -> str:
    """System category for a confirmed pair: Card payment if a credit card is involved."""
    return "card_payment" if "credit_card" in account_types else "own_transfer"
