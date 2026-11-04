"""Statement reconciliation (ARCHITECTURE §7).

Asset accounts:      opening + credits - debits = closing
Liability accounts:  opening + debits - credits = closing   (credit cards: what you owe)

When rows carry a running balance it is walked too; `first_break_seq` is the first row whose
printed balance disagrees with the computed one, which usually points at a mis-parsed row.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from finboard.domain.money import ZERO, to_money

BalanceKind = Literal["asset", "liability"]
ReconStatus = Literal["ok", "mismatch", "unverifiable"]


@dataclass(frozen=True, slots=True)
class ReconRow:
    seq: int
    direction: str  # "debit" | "credit"
    amount: Decimal
    balance_after: Decimal | None


@dataclass(frozen=True, slots=True)
class Reconciliation:
    status: ReconStatus
    credits: Decimal
    debits: Decimal
    expected_closing: Decimal | None
    diff: Decimal | None  # closing - expected_closing
    first_break_seq: int | None


def _effect(kind: BalanceKind, direction: str, amount: Decimal) -> Decimal:
    if direction not in ("debit", "credit"):
        raise ValueError(f"unknown direction {direction!r}")
    sign = 1 if (direction == "credit") == (kind == "asset") else -1
    return amount if sign == 1 else -amount


def reconcile(
    kind: BalanceKind,
    opening: Decimal | None,
    closing: Decimal | None,
    rows: Sequence[ReconRow],
) -> Reconciliation:
    credits = to_money(sum((r.amount for r in rows if r.direction == "credit"), ZERO))
    debits = to_money(sum((r.amount for r in rows if r.direction == "debit"), ZERO))

    first_break = _first_running_break(kind, opening, rows)

    if opening is None or closing is None:
        expected = diff = None
        # Missing totals can't be checked, but a running-balance break is still evidence.
        status: ReconStatus = "mismatch" if first_break is not None else "unverifiable"
    else:
        net = credits - debits if kind == "asset" else debits - credits
        expected = to_money(opening + net)
        diff = to_money(closing - expected)
        status = "ok" if diff == ZERO and first_break is None else "mismatch"

    return Reconciliation(
        status=status,
        credits=credits,
        debits=debits,
        expected_closing=expected,
        diff=diff,
        first_break_seq=first_break,
    )


def _first_running_break(
    kind: BalanceKind, opening: Decimal | None, rows: Sequence[ReconRow]
) -> int | None:
    running = opening
    for row in rows:
        effect = _effect(kind, row.direction, row.amount)
        if running is None:
            # No opening balance: anchor on the first printed balance.
            if row.balance_after is not None:
                running = row.balance_after
            continue
        running = running + effect
        if row.balance_after is not None:
            if row.balance_after != running:
                return row.seq
            running = row.balance_after
    return None
