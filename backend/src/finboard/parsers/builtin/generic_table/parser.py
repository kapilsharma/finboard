"""`generic_table`: a fallback for statements laid out as one transaction table.

It finds a header row by common column names (Date, Description/Narration, Debit/Withdrawal,
Credit/Deposit or Amount with Dr/Cr, Balance), then assigns each word below it to a column by
its x-position. Descriptions that wrap onto following lines are joined. Being generic, it is a
*fallback* parser: it is only chosen when no bank-specific adapter recognises the file
(ADR-0033).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from finboard.parsers.sdk import (
    PARSER_API_VERSION,
    AccountTypeName,
    BalanceKind,
    OpenedDocument,
    ParsedStatement,
    ParsedTransaction,
    ParserError,
    TextLine,
    Word,
)
from finboard.parsers.sdk.helpers import last_digits, parse_date, parse_signed_amount

if TYPE_CHECKING:
    from pydantic import BaseModel

HEADER_SYNONYMS: dict[str, tuple[str, ...]] = {
    "value_date": ("value date", "value dt"),
    "date": ("date", "txn date", "transaction date", "tran date", "posting date", "post date"),
    "description": (
        "description",
        "narration",
        "particulars",
        "details",
        "transaction details",
        "remarks",
    ),
    "debit": ("debit", "debits", "withdrawal", "withdrawals", "withdrawal amt", "debit amount"),
    "credit": ("credit", "credits", "deposit", "deposits", "deposit amt", "credit amount"),
    "amount": ("amount", "amount inr", "amount rs", "transaction amount"),
    "balance": ("balance", "running balance", "balance inr", "closing balance"),
}
NUMERIC_ROLES = ("debit", "credit", "amount", "balance")
_PHRASES: dict[str, str] = {
    phrase: role for role, phrases in HEADER_SYNONYMS.items() for phrase in phrases
}
_MARKERS = {"dr", "cr", "dr.", "cr."}
_NOT_CONTINUATION = re.compile(
    r"opening balance|closing balance|previous balance|total|page \d|statement summary|"
    r"generated|end of statement",
    re.IGNORECASE,
)
_DATE_TOKEN = re.compile(
    r"\b(\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}|\d{1,2}[- ][A-Za-z]{3}[- ]\d{2,4}|\d{4}-\d{2}-\d{2})\b"
)
_MONEY = r"(?:INR|Rs\.?|₹)?\s*([\d,]+\.\d{2})(\s*(?:Dr|Cr)\b)?"
_OPENING = re.compile(r"(?:opening|previous)\s+balance\s*[:\-]?\s*" + _MONEY, re.IGNORECASE)
_CLOSING = re.compile(
    r"(?:closing\s+balance|total\s+(?:amount\s+)?due)\s*[:\-]?\s*" + _MONEY, re.IGNORECASE
)
_ACCOUNT = re.compile(
    r"(?:account|a/c|card)\s*(?:no\.?|number|#)?\s*[:\-]?\s*([X*x\d][X*x\d \-]{3,})",
    re.IGNORECASE,
)
_CONTINUATION_GAP = 20.0  # points between a row and a wrapped description line


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", text.lower())).strip()


@dataclass(frozen=True, slots=True)
class Column:
    role: str
    x0: float
    x1: float

    def gap(self, word: Word) -> float:
        """0 if the word overlaps the header horizontally, else the distance between them."""
        return max(0.0, self.x0 - word.x1, word.x0 - self.x1)


@dataclass
class Layout:
    columns: dict[str, Column]

    @property
    def numeric(self) -> list[Column]:
        return [c for r, c in self.columns.items() if r in NUMERIC_ROLES]

    @property
    def numeric_left(self) -> float:
        return min(c.x0 for c in self.numeric)


@dataclass
class _Row:
    day: date
    top: float
    page: int
    cells: dict[str, list[str]] = field(default_factory=dict)
    value_date: date | None = None

    def add(self, role: str, text: str) -> None:
        self.cells.setdefault(role, []).append(text)

    def cell(self, role: str) -> str:
        return " ".join(self.cells.get(role, []))


def find_header(line: TextLine) -> Layout | None:
    words = line.words
    columns: dict[str, Column] = {}
    i = 0
    while i < len(words):
        for size in (3, 2, 1):
            chunk = words[i : i + size]
            if len(chunk) < size:
                continue
            role = _PHRASES.get(_norm(" ".join(w.text for w in chunk)))
            if role and role not in columns:
                columns[role] = Column(role, chunk[0].x0, chunk[-1].x1)
                i += size
                break
        else:
            i += 1
    has_amounts = ("debit" in columns and "credit" in columns) or "amount" in columns
    if "date" in columns and "description" in columns and has_amounts:
        return Layout(columns)
    return None


def _leading_date(words: tuple[Word, ...], column: Column) -> tuple[date, int] | None:
    """The date at the start of a row (one token, or three like `05 Sep 2026`)."""
    if not words or words[0].x0 > column.x1 + 30:
        return None
    for size in (1, 3):
        if len(words) >= size:
            parsed = parse_date(" ".join(w.text for w in words[:size]))
            if parsed is not None:
                return parsed, size
    return None


class GenericTableParser:
    id = "generic_table"
    name = "Generic table statement (PDF)"
    version = "1.0.0"
    api_version = PARSER_API_VERSION
    institutions: tuple[str, ...] = ()
    account_types: tuple[AccountTypeName, ...] = ("savings", "current", "credit_card")
    file_types = (".pdf",)
    options_schema: type[BaseModel] | None = None
    fallback = True

    def detect(self, doc: OpenedDocument) -> float:
        try:
            if doc.pdf is None:
                return 0.0
            for index in range(min(2, doc.pdf.page_count)):
                for line in doc.pdf.lines(index):
                    layout = find_header(line)
                    if layout is not None:
                        has_balance_info = bool(_OPENING.search(doc.pdf.page_text(index)))
                        return 0.85 if has_balance_info else 0.8
            return 0.0
        except Exception:
            return 0.0

    def parse(self, doc: OpenedDocument, options: BaseModel | None) -> ParsedStatement:
        pdf = doc.pdf
        if pdf is None:
            raise ParserError("Only PDF statements are supported")
        full_text = pdf.text()
        if not full_text.strip():
            raise ParserError("This PDF has no text layer (is it scanned?)")

        rows, warnings = self._rows(doc)
        first_page = pdf.page_text(0)
        kind: BalanceKind = "liability" if "credit card" in first_page.lower() else "asset"
        maybe = [self._transaction(row, kind, warnings) for row in rows]
        transactions = [t for t in maybe if t is not None]
        if len(transactions) >= 2 and transactions[0].date > transactions[-1].date:
            transactions.reverse()  # newest-first statements

        period = self._period(first_page)
        return ParsedStatement(
            institution=self._institution(pdf.lines(0)),
            balance_kind=kind,
            account_hint=self._account_hint(first_page),
            period_start=period[0] if period else None,
            period_end=period[1] if period else None,
            opening_balance=self._balance(_OPENING, full_text, kind),
            closing_balance=self._balance(_CLOSING, full_text, kind),
            transactions=transactions,
            warnings=warnings,
        )

    # ---------------------------------------------------------------- table

    def _rows(self, doc: OpenedDocument) -> tuple[list[_Row], list[str]]:
        assert doc.pdf is not None
        layout: Layout | None = None
        rows: list[_Row] = []
        warnings: list[str] = []
        for page in range(doc.pdf.page_count):
            last_top: float | None = None
            for line in doc.pdf.lines(page):
                header = find_header(line)
                if header is not None:
                    layout, last_top = header, None
                    continue
                if layout is None:
                    continue
                started = _leading_date(line.words, layout.columns["date"])
                if started is not None:
                    rows.append(self._start_row(line, layout, *started))
                    last_top = line.top
                    continue
                if (
                    rows
                    and last_top is not None
                    and rows[-1].page == page
                    and line.top - last_top <= _CONTINUATION_GAP
                    and self._is_description_line(line, layout)
                ):
                    rows[-1].add("description", line.text)
                    last_top = line.top
                else:
                    last_top = None
        if layout is None:
            raise ParserError("No transaction table was found in this statement")
        return rows, warnings

    @staticmethod
    def _is_description_line(line: TextLine, layout: Layout) -> bool:
        desc = layout.columns["description"]
        return (
            not _NOT_CONTINUATION.search(line.text)
            and line.x0 >= desc.x0 - 3
            and line.x1 <= layout.numeric_left - 2
        )

    @staticmethod
    def _start_row(line: TextLine, layout: Layout, day: date, used: int) -> _Row:
        row = _Row(day=day, top=line.top, page=line.page)
        row.add("date", " ".join(w.text for w in line.words[:used]))
        words = list(line.words[used:])
        value_col = layout.columns.get("value_date")
        if value_col and words and value_col.gap(words[0]) < 10:
            parsed = parse_date(words[0].text)
            if parsed is not None:
                row.value_date = parsed
                row.add("value_date", words.pop(0).text)

        numeric = layout.numeric
        last_numeric: str | None = None
        for word in words:
            lowered = word.text.lower()
            if lowered in _MARKERS and last_numeric is not None:
                row.add(last_numeric, word.text)
                continue
            if word.x1 > layout.numeric_left - 5 and parse_signed_amount(word.text) is not None:
                column = min(numeric, key=lambda c: (c.gap(word), abs(c.x1 - word.x1)))
                row.add(column.role, word.text)
                last_numeric = column.role
                continue
            row.add("description", word.text)
            last_numeric = None
        return row

    @staticmethod
    def _transaction(row: _Row, kind: str, warnings: list[str]) -> ParsedTransaction | None:
        debit = parse_signed_amount(row.cell("debit")) if row.cells.get("debit") else None
        credit = parse_signed_amount(row.cell("credit")) if row.cells.get("credit") else None
        amount_cell = parse_signed_amount(row.cell("amount")) if row.cells.get("amount") else None

        if debit and debit[0] > 0 and not (credit and credit[0] > 0):
            amount, direction = debit[0], "debit"
        elif credit and credit[0] > 0 and not (debit and debit[0] > 0):
            amount, direction = credit[0], "credit"
        elif amount_cell and amount_cell[0] > 0:
            amount = amount_cell[0]
            direction = "credit" if amount_cell[1] == "cr" else "debit"
        else:
            warnings.append(f"Skipped a row dated {row.day.isoformat()} with no amount")
            return None

        balance: Decimal | None = None
        if row.cells.get("balance"):
            parsed = parse_signed_amount(row.cell("balance"))
            if parsed is not None:
                balance = _signed(parsed, kind)

        description = row.cell("description").strip()
        if not description:
            warnings.append(f"A row dated {row.day.isoformat()} has no description")
            description = "(no description)"
        return ParsedTransaction(
            date=row.day,
            value_date=row.value_date,
            description=description,
            amount=amount,
            direction="credit" if direction == "credit" else "debit",
            balance_after=balance,
            raw={role: " ".join(parts) for role, parts in row.cells.items() if parts},
        )

    # ---------------------------------------------------------------- statement fields

    @staticmethod
    def _institution(lines: list[TextLine]) -> str:
        for line in lines[:8]:
            if "bank" in line.text.lower():
                return line.text.strip()
        return "Unknown bank"

    @staticmethod
    def _account_hint(text: str) -> str | None:
        match = _ACCOUNT.search(text)
        return last_digits(match.group(1)) if match else None

    @staticmethod
    def _period(text: str) -> tuple[date, date] | None:
        for line in text.splitlines():
            lowered = line.lower()
            if "period" in lowered or lowered.lstrip().startswith("from"):
                dates = [parse_date(m.group(1)) for m in _DATE_TOKEN.finditer(line)]
                found = [d for d in dates if d is not None]
                if len(found) >= 2:
                    return found[0], found[1]
        return None

    @staticmethod
    def _balance(pattern: re.Pattern[str], text: str, kind: str) -> Decimal | None:
        match = pattern.search(text)
        if not match:
            return None
        parsed = parse_signed_amount(match.group(1) + (match.group(2) or ""))
        return None if parsed is None else _signed(parsed, kind)


def _signed(parsed: tuple[Decimal, str | None], kind: str) -> Decimal:
    """Balance sign: an asset balance marked Dr is overdrawn; a card balance marked Cr is
    money the bank owes you."""
    amount, marker = parsed
    negative = marker == ("dr" if kind == "asset" else "cr")
    return -amount if negative else amount
