"""Own-account transfer pairing (ARCHITECTURE §9)."""

import uuid
from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from finboard.categorisation.pairing import (
    PairCandidate,
    suggest_pairs,
    transfer_category_key,
)

SAVINGS, CARD, LOAN, OTHER_SAVINGS = (uuid.uuid4() for _ in range(4))
TYPES = {SAVINGS: "savings", CARD: "credit_card", LOAN: "loan", OTHER_SAVINGS: "savings"}
DAY = date(2026, 9, 10)


def t(
    account: uuid.UUID,
    direction: str,
    amount: str = "5000.00",
    days: int = 0,
    text: str = "",
) -> PairCandidate:
    return PairCandidate(
        id=uuid.uuid4(),
        account_id=account,
        account_type=TYPES[account],
        date=DAY + timedelta(days=days),
        direction=direction,
        amount=D(amount),
        description_norm=text,
    )


def ids(pairs: list) -> set[tuple[uuid.UUID, uuid.UUID]]:
    return {(p.debit_id, p.credit_id) for p in pairs}


@pytest.mark.parametrize(("days", "paired"), [(0, True), (3, True), (-3, True), (4, False)])
def test_within_three_days(days: int, paired: bool) -> None:
    debit, credit = t(SAVINGS, "debit"), t(CARD, "credit", days=days)
    assert (ids(suggest_pairs([debit, credit])) == {(debit.id, credit.id)}) is paired


def test_needs_same_amount_different_account_and_opposite_directions() -> None:
    assert suggest_pairs([t(SAVINGS, "debit"), t(CARD, "credit", amount="5000.01")]) == []
    assert suggest_pairs([t(SAVINGS, "debit"), t(SAVINGS, "credit")]) == []
    assert suggest_pairs([t(SAVINGS, "debit"), t(CARD, "debit")]) == []


def test_one_to_one_closest_date_wins() -> None:
    debit = t(SAVINGS, "debit")
    near, far = t(CARD, "credit", days=1), t(OTHER_SAVINGS, "credit", days=2)
    pairs = suggest_pairs([debit, far, near])
    assert ids(pairs) == {(debit.id, near.id)}


def test_greedy_matching_uses_each_side_once() -> None:
    d1, d2 = t(SAVINGS, "debit", days=0), t(SAVINGS, "debit", days=2)
    c1, c2 = t(CARD, "credit", days=0), t(CARD, "credit", days=2)
    pairs = suggest_pairs([d1, d2, c1, c2])
    assert ids(pairs) == {(d1.id, c1.id), (d2.id, c2.id)}


def test_transfer_hints_break_ties() -> None:
    debit = t(SAVINGS, "debit", text="NEFT CC BILL PAYMENT")
    plain = t(OTHER_SAVINGS, "credit", days=1, text="UPI CR RAVI")
    hinted = t(CARD, "credit", days=1, text="PAYMENT RECEIVED THANK YOU")
    pairs = suggest_pairs([debit, plain, hinted])
    assert ids(pairs) == {(debit.id, hinted.id)}
    assert pairs[0].hints > 0 and 0 < pairs[0].score <= 1


def test_rejected_pairs_are_not_suggested_again() -> None:
    debit, first, second = (
        t(SAVINGS, "debit"),
        t(CARD, "credit"),
        t(OTHER_SAVINGS, "credit", days=1),
    )
    pairs = suggest_pairs([debit, first, second], rejected=[(debit.id, first.id)])
    assert ids(pairs) == {(debit.id, second.id)}


def test_never_pairs_into_loan_insurance_or_mutual_fund() -> None:
    assert suggest_pairs([t(SAVINGS, "debit"), t(LOAN, "credit")]) == []
    assert suggest_pairs([t(LOAN, "debit"), t(SAVINGS, "credit")]) == []


def test_deterministic() -> None:
    txns = [t(SAVINGS, "debit"), t(CARD, "credit"), t(OTHER_SAVINGS, "credit")]
    assert suggest_pairs(txns) == suggest_pairs(list(reversed(txns)))


def test_card_payment_when_a_credit_card_is_involved() -> None:
    assert transfer_category_key(["savings", "credit_card"]) == "card_payment"
    assert transfer_category_key(["savings", "savings"]) == "own_transfer"
