"""The adapter contract (ARCHITECTURE §8). Everything a parser returns is validated here, so the
pipeline after `parse()` can trust its input whichever bank it came from."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pydantic import BaseModel

    from finboard.parsers.sdk.document import OpenedDocument

PARSER_API_VERSION = 1

Direction = Literal["debit", "credit"]
BalanceKind = Literal["asset", "liability"]
# Same values as finboard's account types; kept as plain strings so the SDK stays standalone.
AccountTypeName = Literal[
    "savings", "current", "credit_card", "loan", "mutual_fund", "insurance", "cash", "other"
]


class ParserError(Exception):
    """An expected failure with a message that is safe to show the user.

    Examples: "This doesn't look like an ICICI savings statement", "Scanned PDF: no text layer".
    Never put statement contents (descriptions, amounts) in the message.
    """

    def __init__(self, user_message: str) -> None:
        self.user_message = user_message
        super().__init__(user_message)


def _check_money(name: str, value: object, *, positive: bool = False) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ParserError(f"{name} must be a Decimal")
    if value.as_tuple().exponent != -2:
        raise ParserError(f"{name} must have exactly 2 decimal places")
    if positive and value <= 0:
        raise ParserError(f"{name} must be greater than zero")


@dataclass(frozen=True, slots=True)
class ParsedTransaction:
    date: dt.date
    description: str
    amount: Decimal  # > 0, exactly 2 dp; the sign lives in `direction`
    direction: Direction
    balance_after: Decimal | None = None
    value_date: dt.date | None = None
    raw: dict[str, str] = field(default_factory=dict)  # the source cells, as printed

    def __post_init__(self) -> None:
        _check_money("amount", self.amount, positive=True)
        if self.balance_after is not None:
            _check_money("balance_after", self.balance_after)
        if self.direction not in ("debit", "credit"):
            raise ParserError("direction must be 'debit' or 'credit'")
        if not self.description.strip():
            raise ParserError("description must not be empty")


@dataclass(frozen=True, slots=True)
class ParsedStatement:
    institution: str
    balance_kind: BalanceKind  # credit cards and loans are liabilities
    transactions: list[ParsedTransaction]
    account_hint: str | None = None  # last digits of the account number only (≤ 4)
    period_start: dt.date | None = None
    period_end: dt.date | None = None
    opening_balance: Decimal | None = None
    closing_balance: Decimal | None = None
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.balance_kind not in ("asset", "liability"):
            raise ParserError("balance_kind must be 'asset' or 'liability'")
        if self.account_hint is not None and not (
            self.account_hint.isdigit() and 1 <= len(self.account_hint) <= 4
        ):
            raise ParserError("account_hint must be 1-4 digits")
        for name in ("opening_balance", "closing_balance"):
            value = getattr(self, name)
            if value is not None:
                _check_money(name, value)
        if self.period_start and self.period_end and self.period_start > self.period_end:
            raise ParserError("period_start is after period_end")


@runtime_checkable
class StatementParser(Protocol):
    """A bank adapter. Synchronous and pure: no database, no network, no finboard internals.

    Register it under the `finboard.parsers` entry-point group (ADR-0009). Optional attribute:
    `fallback: bool = True` for generic parsers that should only win when no bank-specific
    parser recognises the file (ADR-0033).
    """

    id: str  # "icici_savings_pdf"
    name: str  # "ICICI Bank — savings account (PDF)"
    version: str  # semver; bump when the output for the same file changes
    api_version: int  # must equal PARSER_API_VERSION
    institutions: tuple[str, ...]
    account_types: tuple[AccountTypeName, ...]
    file_types: tuple[str, ...]  # (".pdf",)
    options_schema: type[BaseModel] | None

    def detect(self, doc: OpenedDocument) -> float:
        """0.0-1.0: how sure you are that this is your format. Cheap, and never raises."""
        ...

    def parse(self, doc: OpenedDocument, options: BaseModel | None) -> ParsedStatement:
        """Turn the document into the canonical statement, or raise ParserError."""
        ...
