"""`icici_savings_pdf`: ICICI Bank savings-account statements (PDF, 2026 layout).

The layout, from `finboard inspect-layout` on a real statement (masked; never the statement):

* Every page starts with "Statement of Transactions in Savings Account XXXXXXXX1234 in INR for
  the period October 01, 2026 - October 31, 2026", then the column header
  `DATE | MODE | PARTICULARS | DEPOSITS | WITHDRAWALS | BALANCE`, and ends with a
  `Total: <deposits> <withdrawals> <balance>` row for that page.
* Dates are `DD-MM-YYYY`. Amounts are right-aligned under their header, so a word's column is
  found from its right edge, never from its text.
* The first row is `B/F` (brought forward) with only a balance: the opening balance.
* PARTICULARS wrap over several lines and the cell is **vertically centred**: the date and
  amounts sit in the middle of the row, with as many particulars lines above them as below.
  Rows have no visible gap between them, so that symmetry is what tells two rows apart.
* MODE (e.g. "CMS TRANSACTION") is usually empty. When present it starts right after the date,
  close enough that the PDF text layer fuses them into one word ("28-10-2026CMS").

The PDF is protected with a user password: the first four letters of the name followed by the
date of birth as DDMM.
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

INSTITUTION = "ICICI Bank"
HEADER = ("date", "mode", "particulars", "deposits", "withdrawals", "balance")
_TITLE = re.compile(r"statement of transactions in savings account", re.IGNORECASE)
_PERIOD = re.compile(
    r"for the period\s+([A-Za-z]+\s+\d{1,2},\s*\d{4})\s*-\s*([A-Za-z]+\s+\d{1,2},\s*\d{4})",
    re.IGNORECASE,
)
_ACCOUNT = re.compile(r"savings account\s+([X*\d]{4,})", re.IGNORECASE)
_LEADING_DATE = re.compile(r"^(\d{2}-\d{2}-\d{4})(.*)$")
_PERIOD_FORMATS = ("%B %d, %Y", "%b %d, %Y", "%B %d,%Y")
_BROUGHT_FORWARD = "b/f"
_COLUMN_TOLERANCE = 8.0  # points between an amount's right edge and its header's right edge
_TABLE_GAP = 40.0  # points: a larger gap below the last table line ends the table


@dataclass(frozen=True, slots=True)
class _Columns:
    mode_x0: float
    particulars_x0: float
    deposits_x1: float
    withdrawals_x1: float
    balance_x1: float

    @classmethod
    def from_header(cls, line: TextLine) -> _Columns | None:
        if tuple(w.text.lower() for w in line.words) != HEADER:
            return None
        _, mode, particulars, deposits, withdrawals, balance = line.words
        return cls(mode.x0, particulars.x0, deposits.x1, withdrawals.x1, balance.x1)

    def amount_column(self, word: Word) -> str | None:
        """'deposits', 'withdrawals' or 'balance' if the word is an amount under one of them."""
        if parse_signed_amount(word.text) is None:
            return None
        edges = {
            "deposits": self.deposits_x1,
            "withdrawals": self.withdrawals_x1,
            "balance": self.balance_x1,
        }
        role, edge = min(edges.items(), key=lambda item: abs(item[1] - word.x1))
        return role if abs(edge - word.x1) <= _COLUMN_TOLERANCE else None


@dataclass
class _Row:
    day: date
    date_text: str
    page: int
    mode: list[str] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)  # particulars, top to bottom
    amounts: dict[str, str] = field(default_factory=dict)
    lines_below_wanted: int = 0


@dataclass
class _PageTotal:
    page: int
    deposits: Decimal | None
    withdrawals: Decimal | None


def _is_header(line: TextLine) -> bool:
    return _Columns.from_header(line) is not None


def _is_total(line: TextLine) -> bool:
    return line.words[0].text.lower().rstrip(":") == "total"


class IciciSavingsPdfParser:
    id = "icici_savings_pdf"
    name = "ICICI Bank — savings account (PDF)"
    version = "1.0.0"
    api_version = PARSER_API_VERSION
    institutions = (INSTITUTION,)
    account_types: tuple[AccountTypeName, ...] = ("savings",)
    file_types = (".pdf",)
    options_schema: type[BaseModel] | None = None

    def detect(self, doc: OpenedDocument) -> float:
        """The six-column header is required; the title line and the bank's name add to it."""
        try:
            if doc.pdf is None or doc.pdf.page_count == 0:
                return 0.0
            if not any(_is_header(line) for line in doc.pdf.lines(0)):
                return 0.0
            first = doc.pdf.page_text(0)
            last = doc.pdf.page_text(doc.pdf.page_count - 1)
            names_bank = "icici" in first.lower() or "icici" in last.lower()
            if _TITLE.search(first):
                return 0.95 if names_bank else 0.9
            return 0.6 if names_bank else 0.4
        except Exception:
            return 0.0  # detect must never raise

    def parse(self, doc: OpenedDocument, options: BaseModel | None) -> ParsedStatement:
        pdf = doc.pdf
        if pdf is None:
            raise ParserError("Only PDF statements are supported")
        first_page = pdf.page_text(0)
        if not first_page.strip():
            raise ParserError("This PDF has no text layer (is it scanned?)")
        if not _TITLE.search(first_page):
            raise ParserError("This doesn't look like an ICICI Bank savings statement")

        warnings: list[str] = []
        rows, opening, totals = self._rows(doc, warnings)
        transactions = [t for t in (self._transaction(r, warnings) for r in rows) if t]
        self._check_page_totals(rows, totals, warnings)

        closing = opening
        if transactions and transactions[-1].balance_after is not None:
            closing = transactions[-1].balance_after
        period = self._period(first_page)
        account = _ACCOUNT.search(first_page)
        return ParsedStatement(
            institution=INSTITUTION,
            balance_kind="asset",
            account_hint=last_digits(account[1]) if account else None,
            period_start=period[0] if period else None,
            period_end=period[1] if period else None,
            opening_balance=opening,
            closing_balance=closing,
            transactions=transactions,
            warnings=warnings,
        )

    # ---------------------------------------------------------------- table

    def _rows(
        self, doc: OpenedDocument, warnings: list[str]
    ) -> tuple[list[_Row], Decimal | None, list[_PageTotal]]:
        """Group the table's lines into rows.

        Particulars lines that come before a row's date line are its upper half; the row then
        takes the same number of lines after its date line, and anything left belongs to the
        next row. The state carries over page breaks, in case a row is ever split across two.
        """
        assert doc.pdf is not None
        rows: list[_Row] = []
        totals: list[_PageTotal] = []
        opening: Decimal | None = None
        pending: list[str] = []  # particulars lines waiting for their row's date line
        found_header = False

        for page in range(doc.pdf.page_count):
            columns: _Columns | None = None
            last_top = 0.0
            for line in doc.pdf.lines(page):
                if columns is None:
                    columns = _Columns.from_header(line)
                    if columns is not None:
                        found_header, last_top = True, line.top
                    continue
                if line.top - last_top > _TABLE_GAP:
                    break
                if _is_total(line):
                    totals.append(self._page_total(page, line, columns))
                    break
                last_top = line.top

                started = self._start_row(line, columns, page)
                if started is not None:
                    if " ".join(started.lines).lower() == _BROUGHT_FORWARD and not (
                        {"deposits", "withdrawals"} & started.amounts.keys()
                    ):
                        opening = self._brought_forward(started, pending, warnings)
                        pending = []
                        continue
                    started.lines[:0] = pending
                    started.lines_below_wanted = len(pending)
                    pending = []
                    rows.append(started)
                    continue

                mode, particulars = self._split_words(line.words, columns)
                current = rows[-1] if rows else None
                if particulars and current is not None and current.lines_below_wanted > 0:
                    current.lines.append(particulars)
                    current.lines_below_wanted -= 1
                elif particulars:
                    pending.append(particulars)
                if mode and current is not None:
                    current.mode.append(mode)

        if not found_header:
            raise ParserError("No transaction table was found in this statement")
        if pending:
            if rows:
                rows[-1].lines.extend(pending)
            warnings.append("Some description lines at the end of the table had no date")
        return rows, opening, totals

    @staticmethod
    def _split_words(words: tuple[Word, ...], columns: _Columns) -> tuple[str, str]:
        """(mode text, particulars text) of a line without a date or amounts."""
        boundary = columns.particulars_x0 - 4
        mode = " ".join(w.text for w in words if w.x0 < boundary)
        particulars = " ".join(
            w.text for w in words if w.x0 >= boundary and columns.amount_column(w) is None
        )
        return mode, particulars

    @staticmethod
    def _start_row(line: TextLine, columns: _Columns, page: int) -> _Row | None:
        first = line.words[0]
        if first.x0 >= columns.mode_x0:
            return None
        match = _LEADING_DATE.match(first.text)
        if match is None:
            return None
        day = parse_date(match[1], ("%d-%m-%Y",))
        if day is None:
            return None
        row = _Row(day=day, date_text=match[1], page=page)
        if match[2]:
            row.mode.append(match[2])  # "28-10-2026CMS": mode fused to the date
        particulars: list[str] = []
        boundary = columns.particulars_x0 - 4
        for word in line.words[1:]:
            role = columns.amount_column(word)
            if role is not None:
                row.amounts[role] = word.text
            elif word.x0 < boundary:
                row.mode.append(word.text)
            else:
                particulars.append(word.text)
        if particulars:
            row.lines.append(" ".join(particulars))
        return row

    @staticmethod
    def _brought_forward(row: _Row, pending: list[str], warnings: list[str]) -> Decimal | None:
        if pending:
            warnings.append("Unexpected text above the opening balance row was ignored")
        parsed = parse_signed_amount(row.amounts.get("balance", ""))
        return None if parsed is None else _signed(parsed)

    @staticmethod
    def _page_total(page: int, line: TextLine, columns: _Columns) -> _PageTotal:
        cells: dict[str, Decimal] = {}
        for word in line.words[1:]:
            role = columns.amount_column(word)
            parsed = parse_signed_amount(word.text)
            if role is not None and parsed is not None:
                cells[role] = parsed[0]
        return _PageTotal(page, cells.get("deposits"), cells.get("withdrawals"))

    @staticmethod
    def _transaction(row: _Row, warnings: list[str]) -> ParsedTransaction | None:
        deposit = parse_signed_amount(row.amounts.get("deposits", ""))
        withdrawal = parse_signed_amount(row.amounts.get("withdrawals", ""))
        credit = deposit[0] if deposit else Decimal(0)
        debit = withdrawal[0] if withdrawal else Decimal(0)
        if credit > 0 and debit > 0:
            raise ParserError(
                f"A row dated {row.day.isoformat()} has both a deposit and a withdrawal"
            )
        if credit == 0 and debit == 0:
            warnings.append(f"Skipped a row dated {row.day.isoformat()} with no amount")
            return None

        balance = parse_signed_amount(row.amounts.get("balance", ""))
        description = " ".join(row.lines).strip() or " ".join(row.mode).strip()
        if not description:
            warnings.append(f"A row dated {row.day.isoformat()} has no description")
            description = "(no description)"
        raw = {"date": row.date_text, "particulars": " ".join(row.lines)}
        if row.mode:
            raw["mode"] = " ".join(row.mode)
        raw.update(row.amounts)
        return ParsedTransaction(
            date=row.day,
            description=description,
            amount=credit if credit > 0 else debit,
            direction="credit" if credit > 0 else "debit",
            balance_after=None if balance is None else _signed(balance),
            raw=raw,
        )

    @staticmethod
    def _check_page_totals(rows: list[_Row], totals: list[_PageTotal], warnings: list[str]) -> None:
        """Each page's `Total:` row must equal the sum of that page's rows: a cheap way to catch
        a row that was read wrongly or missed."""
        for total in totals:
            on_page = [r for r in rows if r.page == total.page]
            for role, printed in (("deposits", total.deposits), ("withdrawals", total.withdrawals)):
                if printed is None:
                    continue
                parsed = [parse_signed_amount(r.amounts.get(role, "")) for r in on_page]
                summed = sum((p[0] for p in parsed if p), Decimal("0.00"))
                if summed != printed:
                    warnings.append(
                        f"The {role} on page {total.page + 1} don't add up to the page total"
                    )

    # ---------------------------------------------------------------- statement fields

    @staticmethod
    def _period(text: str) -> tuple[date, date] | None:
        match = _PERIOD.search(text)
        if match is None:
            return None
        start = parse_date(re.sub(r"\s+", " ", match[1]), _PERIOD_FORMATS)
        end = parse_date(re.sub(r"\s+", " ", match[2]), _PERIOD_FORMATS)
        return (start, end) if start and end else None


def _signed(parsed: tuple[Decimal, str | None]) -> Decimal:
    """An overdrawn savings balance is printed with a leading minus or `Dr`."""
    amount, marker = parsed
    return -amount if marker == "dr" else amount
