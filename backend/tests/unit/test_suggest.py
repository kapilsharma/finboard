"""Rule-from-review suggestions (ARCHITECTURE §9)."""

import pytest

from finboard.categorisation.matcher import MatchKind
from finboard.categorisation.normalise import normalise
from finboard.categorisation.suggest import group_key, merchant_tokens, suggest_rule


def test_swiggy_upi_suggests_contains_swiggy() -> None:
    suggestion = suggest_rule(normalise("UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment"))
    assert suggestion is not None
    assert suggestion.match_kind is MatchKind.CONTAINS
    assert suggestion.pattern == "SWIGGY"


@pytest.mark.parametrize(
    ("raw", "pattern"),
    [
        ("POS 4111XXXXXXXX1234 AMAZON IN", "AMAZON"),
        ("UPI-ZOMATO-ZOMATO.ORDER@ICICI-ICIC0DC0099-612345678901-UPI", "ZOMATO"),
        ("BIL/ONL/000123456789/AIRTEL/Bill", "AIRTEL"),
        ("NEFT-HDFCN52026091234567-ACME CORP-SALARY SEP", "ACME"),
        ("VPS*XXXX-4321*HPCL PETROL PUMP", "HPCL"),
        ("RELIANCE FRESH BANGALORE IN", "RELIANCE"),
        ("IMPS/975288200182/REFUND/APOLLO PHARMACY", "APOLLO"),
        ("REFUND UBER INDIA", "UBER"),
    ],
)
def test_suggestions(raw: str, pattern: str) -> None:
    suggestion = suggest_rule(normalise(raw))
    assert suggestion is not None and suggestion.pattern == pattern


def test_stop_words_digits_and_short_tokens_are_dropped() -> None:
    assert merchant_tokens("UPI DR NEFT IMPS YBL OKSBI PAYMENT 2026 AB X1Y KFC") == ["KFC"]


def test_nothing_usable() -> None:
    assert suggest_rule(normalise("UPI/DR/412345678901/YESB/Payment")) is None
    assert group_key("") is None


def test_the_first_merchant_token_wins_over_a_longer_later_one() -> None:
    assert group_key("UPI KFC KORAMANGALA") == "KFC"
    assert suggest_rule(normalise("PAYMENT RECEIVED - THANK YOU")) is None


def test_the_suggestion_matches_its_own_transaction() -> None:
    text = normalise("UPI/DR/412345678901/BIGBASKET/YESB/bb@ybl/Order")
    suggestion = suggest_rule(text)
    assert suggestion is not None and suggestion.pattern in text
