"""The starter rule pack is valid and categorises typical Indian narrations as intended."""

import uuid
from decimal import Decimal

import pytest

from finboard.categorisation.matcher import CompiledRules, RuleSpec, TxnFacts, validate_pattern
from finboard.categorisation.normalise import normalise
from finboard.seed.categories import DEFAULT_CATEGORIES
from finboard.seed.rules import STARTER_RULES

CATEGORY_IDS = {c.name: uuid.uuid5(uuid.NAMESPACE_URL, c.name) for c in DEFAULT_CATEGORIES}
NAMES = {v: k for k, v in CATEGORY_IDS.items()}


def compiled() -> CompiledRules:
    return CompiledRules.compile(
        RuleSpec(
            id=uuid.UUID(int=i + 1),
            priority=i,
            match_kind=seed.match_kind,
            pattern=seed.pattern,
            category_id=CATEGORY_IDS[seed.category],
            direction=seed.direction.value if seed.direction else None,
        )
        for i, seed in enumerate(STARTER_RULES)
    )


def test_every_rule_is_valid_and_points_at_a_default_category() -> None:
    for seed in STARTER_RULES:
        validate_pattern(seed.match_kind, seed.pattern)
        assert seed.category in CATEGORY_IDS, seed


@pytest.mark.parametrize(
    ("raw", "direction", "category"),
    [
        ("UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment", "debit", "Dining out"),
        ("POS XX1234 ZOMATO LTD", "debit", "Dining out"),
        ("UPI/DR/412345678902/BIGBASKET/YESB/bb@ybl/Order", "debit", "Groceries"),
        ("POS 4111XXXXXXXX1234 DMART AVENUE", "debit", "Groceries"),
        ("VPS*XXXX-4321*HPCL PETROL PUMP", "debit", "Transport"),
        ("IRCTC CF 612345678901", "debit", "Transport"),
        ("POS XX1234 AMAZON IN", "debit", "Shopping"),
        ("UPI/DR/412345678903/FLIPKART/YESB/fk@ybl/Pay", "debit", "Shopping"),
        ("BIL/ONL/000123456789/AIRTEL/Bill", "debit", "Utilities"),
        ("UPI/DR/412345678904/JIO PREPAID/YESB/jio@ybl/Recharge", "debit", "Utilities"),
        ("CC BILL PAYMENT - 4375XXXXXXXX9012", "debit", "Card payment"),
        ("INFT/CC PAYMENT/ICICI CARD", "debit", "Card payment"),
        ("ECS/ICICI PRU MF/SIP 1234567", "debit", "Investments"),
        ("ACH D- GLOBEX PVT LTD SIP 123456", "debit", "Investments"),
        ("NACH_DR_LIC OF INDIA_000098765432", "debit", "Insurance"),
        ("ATM WDL XX1234 MG ROAD", "debit", "Cash"),
        ("NFS/CASH WDL/123456/PUNE", "debit", "Cash"),
        ("HDFC LTD EMI 1234567890", "debit", "Loan EMI"),
        ("NEFT-HDFCN52026091234567-ACME CORP-SALARY SEP", "credit", "Salary"),
        ("INT.PD:01-09-2026 TO 30-09-2026", "credit", "Interest"),
        ("INTEREST CREDITED", "credit", "Interest"),
    ],
)
def test_typical_narrations(raw: str, direction: str, category: str) -> None:
    rule = compiled().first_match(TxnFacts(normalise(raw), direction, Decimal("100.00")))
    assert rule is not None, raw
    assert NAMES[rule.category_id] == category


@pytest.mark.parametrize(
    ("raw", "direction"),
    [
        ("UPI/CR/412345678901/SWIGGY LTD/YESB/Refund", "credit"),  # refunds aren't spending
        ("GOSSIP MAGAZINE SUBSCRIPTION", "debit"),  # SIP only as a word
        ("UPI/DR/412345678905/RAVI KUMAR/SBIN/ravi@oksbi/Dinner", "debit"),
    ],
)
def test_no_false_positives(raw: str, direction: str) -> None:
    assert compiled().first_match(TxnFacts(normalise(raw), direction, Decimal("1.00"))) is None
