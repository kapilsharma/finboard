import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from hypothesis import given
from hypothesis import strategies as st

from finboard.domain.fingerprint import (
    FingerprintInput,
    dedupe_desc,
    find_possible_duplicates,
    fingerprint,
    fingerprints,
)
from finboard.domain.money import is_money, parse_amount, to_money

ACCOUNT = uuid.UUID("01900000-0000-7000-8000-000000000001")


# ---------------------------------------------------------------- money


def test_floats_are_rejected() -> None:
    with pytest.raises(TypeError):
        to_money(0.1)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        to_money(True)  # type: ignore[arg-type]


def test_quantises_half_up() -> None:
    assert to_money("1.005") == D("1.01")
    assert to_money(D("2")) == D("2.00")
    assert to_money(7) == D("7.00")


def test_rejects_nan_and_overflow() -> None:
    with pytest.raises(ValueError, match="finite"):
        to_money(D("NaN"))
    with pytest.raises(ValueError, match="range"):
        to_money("1000000000000.00")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("1,23,456.78", "123456.78"),
        ("1,234,567.00", "1234567.00"),
        ("50", "50.00"),
        ("-3.5", "-3.50"),
    ],
)
def test_parse_amount(text: str, value: str) -> None:
    assert parse_amount(text) == D(value)


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "12,34", "1e5"])
def test_parse_amount_rejects(text: str) -> None:
    assert parse_amount(text) is None


@given(st.decimals(min_value=D("-1e11"), max_value=D("1e11"), places=2, allow_nan=False))
def test_to_money_is_idempotent(value: D) -> None:
    once = to_money(value)
    assert to_money(once) == once and is_money(once)


# ---------------------------------------------------------------- fingerprint


def row(
    desc: str = "UPI/412345678901/SWIGGY", amount: str = "250.00", bal: str | None = "1000.00"
) -> FingerprintInput:
    return FingerprintInput(
        date=date(2026, 9, 1),
        direction="debit",
        amount=D(amount),
        description_raw=desc,
        balance_after=None if bal is None else D(bal),
    )


def test_dedupe_desc_is_nfkc_upper_collapsed() -> None:
    # Full-width letters (U+FF41…); NFKC folds them to ASCII.
    fullwidth_swiggy = "".join(chr(0xFF41 + ord(c) - ord("a")) for c in "swiggy")
    assert dedupe_desc(f"  upi/{fullwidth_swiggy} \t  ltd ") == "UPI/SWIGGY LTD"


def test_fingerprint_is_stable_and_versioned() -> None:
    first = fingerprint(ACCOUNT, row(), 0)
    assert first == fingerprint(ACCOUNT, row(), 0)
    assert len(first) == 64
    # Frozen format (ADR-0016): if this changes, every existing user gets duplicates.
    assert first == fingerprint(ACCOUNT, row(desc="upi/412345678901/swiggy"), 0)


def test_fingerprint_depends_on_every_field() -> None:
    base = fingerprint(ACCOUNT, row(), 0)
    assert fingerprint(uuid.uuid4(), row(), 0) != base
    assert fingerprint(ACCOUNT, row(amount="250.01"), 0) != base
    assert fingerprint(ACCOUNT, row(bal=None), 0) != base
    assert fingerprint(ACCOUNT, row(desc="UPI/412345678902/SWIGGY"), 0) != base
    assert fingerprint(ACCOUNT, row(), 1) != base


def test_identical_rows_in_one_statement_get_seq_in_day() -> None:
    same = row(bal=None)
    prints = fingerprints(ACCOUNT, [same, same, row(desc="OTHER", bal=None), same])
    assert len(set(prints)) == 4
    # Re-importing the same statement reproduces the same fingerprints.
    assert prints == fingerprints(ACCOUNT, [same, same, row(desc="OTHER", bal=None), same])


def test_possible_duplicates_flag_same_money_different_text() -> None:
    rows = [row(desc="SWIGGY ORDER 1"), row(desc="SWIGGY ORDER 1 TRUNCATED"), row(amount="9.00")]
    assert find_possible_duplicates(rows) == [(0, 1)]
