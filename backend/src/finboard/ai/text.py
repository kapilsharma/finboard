"""What gets embedded for category suggestions (M3a): the merchant words of a normalised
description, without the narration's boilerplate.

Bank narrations share a lot of format text (`UPI DR … YESB … @ybl PAYMENT`). Left in, it
makes unrelated merchants look alike, and no similarity cut-off can tell "the same merchant"
from "the same bank's format" (docs/ai-eval.md). The rule suggester's `merchant_tokens`
already drops channels, markers and numbers; this also drops bank codes, UPI handles and
payment filler words.
"""

from __future__ import annotations

from finboard.categorisation.suggest import merchant_tokens

TEXT_VERSION = 1  # bump when match_text changes: stored embeddings are then rebuilt

FILLER = frozenset(
    {
        # bank codes in IFSC / UPI narrations
        "HDFC", "ICIC", "SBIN", "UTIB", "KKBK", "YESB", "PUNB", "BARB", "CNRB", "IDIB",
        "INDB", "IDFB", "FDRL", "UBIN", "BKID", "MAHB", "IOBA", "CBIN", "UCBA", "RATN",
        "HDFCN", "ICICI", "AXIS", "KOTAK",
        # UPI handles
        "YBL", "IBL", "AXL", "APL", "OKAXIS", "OKHDFCBANK", "OKICICI", "OKSBI", "PAYTM",
        "UPI", "PTYES", "PTAXIS", "WAICICI", "WAHDFCBANK",
        # payment filler
        "PAYMENT", "PAY", "COLLECT", "BILL", "PURCHASE", "SENT", "RECEIVED", "REQUEST",
    }
)  # fmt: skip


def match_text(description_norm: str) -> str:
    """'UPI DR YESB SWIGGY swiggy@ybl PAYMENT' -> 'SWIGGY SWIGGY'. Empty when nothing names
    a merchant, and then there is nothing to suggest from."""
    return " ".join(t for t in merchant_tokens(description_norm.upper()) if t not in FILLER)


def embedding_key(model: str) -> str:
    """What `txn_embedding.model` stores: the model and the text version."""
    return f"{model}#text{TEXT_VERSION}"
