"""Rule matching (ARCHITECTURE §9, ADR-0020): order, constraints, kinds, regex timeout."""

import uuid
from decimal import Decimal as D

import pytest

from finboard.categorisation.matcher import (
    MAX_PATTERN_LENGTH,
    CompiledRules,
    InvalidPattern,
    MatchKind,
    RuleSpec,
    TxnFacts,
    validate_pattern,
)

FOOD, SHOP, OTHER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
ACC_A, ACC_B = uuid.uuid4(), uuid.uuid4()


def rule(
    pattern: str,
    *,
    kind: MatchKind = MatchKind.CONTAINS,
    priority: int = 0,
    category: uuid.UUID = FOOD,
    rule_id: uuid.UUID | None = None,
    **constraints: object,
) -> RuleSpec:
    return RuleSpec(
        id=rule_id or uuid.uuid4(),
        priority=priority,
        match_kind=kind,
        pattern=pattern,
        category_id=category,
        **constraints,  # type: ignore[arg-type]
    )


def txn(text: str, direction: str = "debit", amount: str = "100.00", account=ACC_A) -> TxnFacts:
    return TxnFacts(
        description_norm=text, direction=direction, amount=D(amount), account_id=account
    )


def test_first_match_by_priority_then_id() -> None:
    low_id, high_id = uuid.UUID(int=1), uuid.UUID(int=2)
    rules = [
        rule("SWIGGY", priority=5, category=OTHER),
        rule("SWIGGY", priority=1, category=SHOP, rule_id=high_id),
        rule("SWIGGY", priority=1, category=FOOD, rule_id=low_id),
    ]
    matched = CompiledRules.compile(rules).first_match(txn("UPI DR SWIGGY LTD"))
    assert matched is not None and matched.id == low_id and matched.category_id == FOOD


def test_no_match_returns_none() -> None:
    assert CompiledRules.compile([rule("ZOMATO")]).first_match(txn("UPI SWIGGY")) is None


@pytest.mark.parametrize(
    ("kind", "pattern", "text", "expected"),
    [
        (MatchKind.CONTAINS, "swiggy", "UPI DR SWIGGY LTD", True),
        (MatchKind.CONTAINS, "swiggy/ltd", "UPI DR SWIGGY LTD", True),  # pattern is normalised
        (MatchKind.STARTS_WITH, "UPI DR", "UPI DR SWIGGY", True),
        (MatchKind.STARTS_WITH, "SWIGGY", "UPI DR SWIGGY", False),
        (MatchKind.EQUALS, "atm wdl", "ATM WDL", True),
        (MatchKind.EQUALS, "ATM", "ATM WDL", False),
        (MatchKind.REGEX, r"\bsip\b", "ECS ICICI PRU MF SIP", True),  # case-insensitive
        (MatchKind.REGEX, r"\bSIP\b", "GOSSIP MAGAZINE", False),
    ],
)
def test_match_kinds(kind: MatchKind, pattern: str, text: str, expected: bool) -> None:
    matched = CompiledRules.compile([rule(pattern, kind=kind)]).first_match(txn(text))
    assert (matched is not None) is expected


def test_constraints_are_anded_with_the_pattern() -> None:
    spec = rule(
        "AMAZON",
        direction="debit",
        account_id=ACC_A,
        amount_min=D("100.00"),
        amount_max=D("500.00"),
    )
    compiled = CompiledRules.compile([spec])
    assert compiled.first_match(txn("POS AMAZON", amount="100.00")) is not None
    assert compiled.first_match(txn("POS AMAZON", amount="500.00")) is not None
    # each constraint alone is enough to fail the rule
    assert compiled.first_match(txn("POS FLIPKART")) is None
    assert compiled.first_match(txn("POS AMAZON", direction="credit")) is None
    assert compiled.first_match(txn("POS AMAZON", account=ACC_B)) is None
    assert compiled.first_match(txn("POS AMAZON", amount="99.99")) is None
    assert compiled.first_match(txn("POS AMAZON", amount="500.01")) is None


def test_a_later_rule_wins_when_an_earlier_constraint_fails() -> None:
    rules = [
        rule("AMAZON", priority=0, category=SHOP, direction="credit"),
        rule("AMAZON", priority=1, category=OTHER),
    ]
    matched = CompiledRules.compile(rules).first_match(txn("POS AMAZON"))
    assert matched is not None and matched.category_id == OTHER


def test_all_matches_lists_shadowing_rules_in_order() -> None:
    first, second = rule("AMAZON", priority=0), rule("AMAZON PRIME", priority=1)
    found = CompiledRules.compile([second, first]).all_matches(txn("AMAZON PRIME VIDEO"))
    assert [r.id for r in found] == [first.id, second.id]


def test_regex_timeout_disables_the_rule_for_the_run() -> None:
    evil = rule(r"(A|AA)+$", kind=MatchKind.REGEX, priority=0, category=OTHER)
    fallback = rule("A", priority=1, category=SHOP)
    compiled = CompiledRules.compile([evil, fallback])
    matched = compiled.first_match(txn("A" * 60 + "B"))
    assert compiled.timed_out == {evil.id}
    assert matched is not None and matched.id == fallback.id  # the run carries on
    # disabled from now on, even for text it would match quickly
    assert compiled.first_match(txn("AAA")) == fallback


def test_invalid_stored_patterns_are_skipped_not_fatal() -> None:
    broken = rule("(unclosed", kind=MatchKind.REGEX)
    ok = rule("SWIGGY", priority=1)
    compiled = CompiledRules.compile([broken, ok])
    assert compiled.invalid == {broken.id}
    assert compiled.first_match(txn("SWIGGY")) == ok


@pytest.mark.parametrize(
    ("kind", "pattern"),
    [
        (MatchKind.REGEX, "(unclosed"),
        (MatchKind.REGEX, "   "),
        (MatchKind.CONTAINS, " // "),
        (MatchKind.CONTAINS, "412345678901"),  # only a reference number: nothing left to match
        (MatchKind.CONTAINS, "A" * (MAX_PATTERN_LENGTH + 1)),
    ],
)
def test_validate_pattern_rejects(kind: MatchKind, pattern: str) -> None:
    with pytest.raises(InvalidPattern):
        validate_pattern(kind, pattern)


def test_validate_pattern_accepts() -> None:
    validate_pattern(MatchKind.REGEX, r"\b(SIP|MF)\b")
    validate_pattern(MatchKind.CONTAINS, "swiggy")
