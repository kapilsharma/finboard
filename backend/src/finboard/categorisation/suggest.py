"""Rule suggestion from a transaction under review (ARCHITECTURE §9, "Rule from review").

Tokenise the normalised description, drop channel and bank words (UPI, NEFT, POS, DR, YBL, …),
generic words (REFUND, ORDER, …), tokens with digits and very short tokens, and propose
`contains <first remaining token>`. The same token groups the review queue, so similar
transactions can be categorised together.

The first token, not the longest (as ARCHITECTURE §9 first said): narrations put the merchant
first and a city or description after it, so "RELIANCE FRESH BANGALORE IN" gives RELIANCE, not
BANGALORE, and "HPCL PETROL PUMP" gives HPCL (ADR-0035).

    UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment  →  contains SWIGGY
"""

from __future__ import annotations

from dataclasses import dataclass

from finboard.categorisation.matcher import MatchKind

# Payment channels, transaction-type markers, common bank / UPI handle codes and filler words.
STOP_WORDS = frozenset(
    [
        "UPI",
        "NEFT",
        "RTGS",
        "IMPS",
        "POS",
        "ECS",
        "NACH",
        "ACH",
        "ATM",
        "CMS",
        "BIL",
        "BILLPAY",
        "BBPS",
        "INB",
        "NET",
        "NETBANKING",
        "MB",
        "MOB",
        "IB",
        "DR",
        "CR",
        "TRF",
        "TRANSFER",
        "TXN",
        "TRAN",
        "TRANS",
        "REF",
        "REFNO",
        "NO",
        "RRN",
        "UTR",
        "CHQ",
        "CHEQUE",
        "CLG",
        "INWARD",
        "OUTWARD",
        "P2A",
        "P2M",
        "P2P",
        "PAYMENT",
        "PAYMENTS",
        "PAY",
        "PAID",
        "PURCHASE",
        "SALE",
        "DEBIT",
        "CREDIT",
        "CARD",
        "VISA",
        "MASTERCARD",
        "RUPAY",
        "YBL",
        "YESB",
        "OKAXIS",
        "OKHDFCBANK",
        "OKICICI",
        "OKSBI",
        "OKBIZAXIS",
        "AXL",
        "IBL",
        "PAYTM",
        "APL",
        "IKWIK",
        "UPIHDFC",
        "ICICI",
        "HDFC",
        "SBIN",
        "UTIB",
        "ICIC",
        "KKBK",
        "HSBC",
        "CSBK",
        "BARB",
        "PUNB",
        "IDFB",
        "INDB",
        "FDRL",
        "BANK",
        "LTD",
        "LIMITED",
        "PVT",
        "PRIVATE",
        "INDIA",
        "IN",
        "THE",
        "AND",
        "FOR",
        "OF",
        "TO",
        "FROM",
        "BY",
        "AT",
        "ON",
        "WITH",
        "COM",
        "WWW",
        "HTTP",
        "HTTPS",
        "SERVICES",
        "SERVICE",
        "INSTA",
        "COLLECT",
        "REQUEST",
        "MANDATE",
        "AUTOPAY",
        "SI",
        "AUTO",
        "VPA",
        "MR",
        "MRS",
        "MS",
        "SHRI",
        "SMT",
        "JAN",
        "FEB",
        "MAR",
        "APR",
        "MAY",
        "JUN",
        "JUL",
        "AUG",
        "SEP",
        "SEPT",
        "OCT",
        "NOV",
        "DEC",
        "ONL",
        "WDL",
        "VPS",
        "REFUND",
        "REVERSAL",
        "RECEIVED",
        "THANK",
        "YOU",
        "OWN",
        "ACCOUNT",
        "SELF",
        "ORDER",
        "ONLINE",
    ]
)
MIN_TOKEN_LENGTH = 3


@dataclass(frozen=True, slots=True)
class RuleSuggestion:
    match_kind: MatchKind
    pattern: str


def merchant_tokens(description_norm: str) -> list[str]:
    """The tokens that could name a merchant, in order."""
    return [
        token
        for token in description_norm.replace(".", " ").split()
        if len(token) >= MIN_TOKEN_LENGTH
        and token not in STOP_WORDS
        and not any(ch.isdigit() for ch in token)
    ]


def suggest_rule(description_norm: str) -> RuleSuggestion | None:
    """`contains <first merchant token>`, or None if nothing usable is left."""
    tokens = merchant_tokens(description_norm)
    if not tokens:
        return None
    return RuleSuggestion(MatchKind.CONTAINS, tokens[0])


def group_key(description_norm: str) -> str | None:
    """The review-queue group a transaction belongs to (its suggested pattern)."""
    suggestion = suggest_rule(description_norm)
    return suggestion.pattern if suggestion else None
