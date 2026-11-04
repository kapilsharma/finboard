"""Description normalisation (ARCHITECTURE §9). Rules match against the result, not the raw text.

Bank narrations carry reference numbers (UPI RRNs, NEFT/IMPS references, card masks) that differ
on every transaction. Removing them leaves the merchant and channel words that rules can match:

    UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment
    → UPI DR SWIGGY LTD YESB SWIGGY YBL PAYMENT

Steps, in order: NFKC + upper-case; remove card masks (`XX1234`, `4111XXXXXXXX1234`,
`****1234`); turn separators (`/ - * _ : @ |`) into spaces; remove tokens that carry a
reference (any token with a run of 6 or more digits, such as `412345678901` or
`N123241234567890`) and IFSC branch codes (`ICIC0DC0099`); collapse whitespace. The result is
idempotent: normalising it again changes nothing.

Bump NORMALISER_VERSION whenever the output changes; `rules.apply` rewrites stored text.
"""

from __future__ import annotations

import re
import unicodedata

NORMALISER_VERSION = 1

# A card mask: optional leading digits, two or more X or *, then 2-4 digits (XX1234,
# 4111XXXXXXXX1234, ****1234, XXXX-1234 is handled after separators by the token rule below).
_CARD_MASK = re.compile(r"\d*[X*]{2,}\d{2,4}\b")
_SEPARATORS = re.compile(r"[/\-*_:@|\\]+")
# A token containing a run of 6+ digits is a reference number (RRN, UTR, NEFT/IMPS ref, cheque).
_REFERENCE = re.compile(r"\S*\d{6,}\S*")
# After separators are spaces: a lone mask such as "XXXX 1234" from "XXXX-1234".
_SPLIT_MASK = re.compile(r"(?<!\S)[X*]{2,}\s+\d{2,4}(?!\S)")
# An IFSC branch code (4 letters, a zero, 6 letters/digits) differs per branch, like a reference.
_IFSC = re.compile(r"(?<!\S)[A-Z]{4}0[A-Z0-9]{6}(?!\S)")
_SPACES = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Return the matchable form of a bank narration (pure, idempotent)."""
    # NFKC again after upper(): upper-casing can produce characters NFKC would change.
    value = unicodedata.normalize("NFKC", unicodedata.normalize("NFKC", text).upper())
    value = _CARD_MASK.sub(" ", value)
    value = _SEPARATORS.sub(" ", value)
    value = _SPLIT_MASK.sub(" ", value)
    value = _REFERENCE.sub(" ", value)
    value = _IFSC.sub(" ", value)
    return _SPACES.sub(" ", value).strip()
