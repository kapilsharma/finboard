"""TEMPLATE adapter — copy this folder to start a new bank (see CONTRIBUTING.md > How to add your
bank). It parses the made-up "Example Bank" savings layout, one transaction per line:

    05/09/2026  UPI/412345678901/SWIGGY LTD/PAYMENT   1,234.00   0.00   45,678.90
    date        narration                          withdrawal deposit  balance

Steps for a real bank:
 1. Rename the folder and class, set `id`, `name`, `institutions`, `account_types`.
 2. Run `finboard inspect-layout your.pdf` and look at the masked structure.
 3. Make `detect()` look for text only that bank's statements have.
 4. Write `parse()`; raise `ParserError` with a user-safe message when the layout is off.
 5. Write `fixtures.py` to draw the same layout with fake data, register both entry points in
    pyproject.toml, and run `uv run pytest tests/parsers`.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from finboard.parsers.sdk import (
    PARSER_API_VERSION,
    AccountTypeName,
    OpenedDocument,
    ParsedStatement,
    ParsedTransaction,
    ParserError,
)
from finboard.parsers.sdk.helpers import last_digits, parse_amount, parse_date

if TYPE_CHECKING:
    from pydantic import BaseModel

_ROW = re.compile(
    r"^(?P<date>\d{2}/\d{2}/\d{4})\s+(?P<narration>.+?)\s+"
    r"(?P<withdrawal>[\d,]+\.\d{2})\s+(?P<deposit>[\d,]+\.\d{2})\s+(?P<balance>[\d,]+\.\d{2})$"
)
_ACCOUNT = re.compile(r"A/c No\.?\s*:?\s*(\S+)")
_PERIOD = re.compile(r"From\s+(\d{2}/\d{2}/\d{4})\s+To\s+(\d{2}/\d{2}/\d{4})")
_OPENING = re.compile(r"Opening Balance\s+([\d,]+\.\d{2})")
_CLOSING = re.compile(r"Closing Balance\s+([\d,]+\.\d{2})")
MARKER = "EXAMPLE BANK"


class ExampleBankSavingsParser:
    id = "example_bank_savings_pdf"
    name = "Example Bank — savings account (PDF, template)"
    version = "1.0.0"
    api_version = PARSER_API_VERSION
    institutions = ("Example Bank",)
    account_types: tuple[AccountTypeName, ...] = ("savings",)
    file_types = (".pdf",)
    options_schema: type[BaseModel] | None = None

    def detect(self, doc: OpenedDocument) -> float:
        try:
            if doc.pdf is None or doc.pdf.page_count == 0:
                return 0.0
            text = doc.pdf.page_text(0)
            if MARKER in text and "Savings Account Statement" in text:
                return 0.95
            return 0.0
        except Exception:
            return 0.0  # detect must never raise

    def parse(self, doc: OpenedDocument, options: BaseModel | None) -> ParsedStatement:
        if doc.pdf is None:
            raise ParserError("Only PDF statements are supported")
        text = doc.pdf.text()
        if MARKER not in text:
            raise ParserError("This doesn't look like an Example Bank statement")

        transactions: list[ParsedTransaction] = []
        for line in text.splitlines():
            match = _ROW.match(line.strip())
            if not match:
                continue
            day = parse_date(match["date"])
            withdrawal = parse_amount(match["withdrawal"])
            deposit = parse_amount(match["deposit"])
            balance = parse_amount(match["balance"])
            if day is None or withdrawal is None or deposit is None or balance is None:
                raise ParserError("A transaction row couldn't be read")
            if (withdrawal > 0) == (deposit > 0):
                raise ParserError("A row has both or neither of withdrawal and deposit")
            transactions.append(
                ParsedTransaction(
                    date=day,
                    description=match["narration"],
                    amount=withdrawal if withdrawal > 0 else deposit,
                    direction="debit" if withdrawal > 0 else "credit",
                    balance_after=balance,
                    raw=dict(match.groupdict()),
                )
            )

        account = _ACCOUNT.search(text)
        period = _PERIOD.search(text)
        opening = _OPENING.search(text)
        closing = _CLOSING.search(text)
        return ParsedStatement(
            institution="Example Bank",
            balance_kind="asset",
            account_hint=last_digits(account[1]) if account else None,
            period_start=parse_date(period[1]) if period else None,
            period_end=parse_date(period[2]) if period else None,
            opening_balance=parse_amount(opening[1]) if opening else None,
            closing_balance=parse_amount(closing[1]) if closing else None,
            transactions=transactions,
        )
