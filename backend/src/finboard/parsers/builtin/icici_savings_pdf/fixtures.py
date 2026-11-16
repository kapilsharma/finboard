"""Synthetic ICICI savings statements (reportlab). Test-time only; never commit the output.

Reproduces the *layout* described in `parser.py` (positions measured with
`finboard inspect-layout`): the title line and column header on every page, the `B/F` row,
vertically centred PARTICULARS cells that wrap at about 196 pt (breaking over-long tokens
mid-token, as the bank does), MODE fused to the date, a `Total:` row per page and the bank's
name in the page-1 header and last-page footer. All values are fake (`synthetic_statement`).
"""

from __future__ import annotations

import io
import random
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from finboard.parsers.sdk import ParsedStatement, ParsedTransaction
from finboard.parsers.sdk.testing import encrypt_pdf, indian_grouping, synthetic_statement

FONT, BOLD, SIZE = "Helvetica", "Helvetica-Bold", 7
LINE = 8.5  # points between wrapped particulars lines
SINGLE_ROW_PAD = 3.0  # one-line rows get a little extra room, as in the real statement
X_DATE, X_MODE_HEADER, X_PARTICULARS = 35.0, 77.0, 144.0
X_DEPOSITS, X_WITHDRAWALS, X_BALANCE = 407.0, 486.0, 559.0  # right edges
WRAP_WIDTH = 196.0  # 144 → 340
BOTTOM = 90.0
DATE_FMT = "%d-%m-%Y"
PERIOD_FMT = "%B %d, %Y"
_ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


@dataclass(frozen=True, slots=True)
class IciciRow:
    """One table row as printed. Amount cells are strings so tests can draw odd values."""

    date: date
    particulars: str
    deposit: str = ""
    withdrawal: str = ""
    balance: str = ""
    mode: str = ""


def wrap(text: str) -> list[str]:
    """Word-wrap at WRAP_WIDTH; a token wider than a whole line is broken mid-token."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if stringWidth(candidate, FONT, SIZE) <= WRAP_WIDTH:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        while stringWidth(current, FONT, SIZE) > WRAP_WIDTH:
            cut = len(current)
            while stringWidth(current[:cut], FONT, SIZE) > WRAP_WIDTH:
                cut -= 1
            lines.append(current[:cut])
            current = current[cut:]
    lines.append(current)
    return lines


def render(
    rows: Sequence[IciciRow],
    *,
    opening: Decimal,
    account_hint: str,
    period: tuple[date, date],
    encrypted_with: str | None = None,
    misprint_withdrawal_total: Decimal = Decimal("0.00"),
) -> bytes:
    """Draw a statement with exactly these rows. Page totals are computed from them, plus
    `misprint_withdrawal_total` on every page (to test the parser's cross-check)."""
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1)
    canvas.setTitle("Statement")
    _, height = A4

    def top(y_from_top: float) -> float:
        return height - y_from_top

    def text(x: float, y: float, value: str, *, bold: bool = False, right: bool = False) -> None:
        canvas.setFont(BOLD if bold else FONT, SIZE)
        if right:
            canvas.drawRightString(x, top(y), value)
        else:
            canvas.drawString(x, top(y), value)

    title = (
        f"Statement of Transactions in Savings Account XXXXXXXX{account_hint} in INR for the "
        f"period {period[0].strftime(PERIOD_FMT)} - {period[1].strftime(PERIOD_FMT)}"
    )

    def first_page_header() -> float:
        text(34, 85, "000123/00000000-00000/0-0/ABCDE/00-00")
        text(406, 97, "Your Base Branch : ICICI BANK, SAMPLE NAGAR")
        text(34, 115, "MR.TEST CUSTOMER")
        text(34, 126, "FLAT 1, EXAMPLE SOCIETY, SAMPLE ROAD")
        text(409, 138, "Website: www.icici.bank.in")
        text(34, 153, "MAHARASHTRA - INDIA - 400001")
        text(37, 262, "Account Type", bold=True)
        text(403, 262, "Account Balance", bold=True)
        text(481, 262, "Nomination Status", bold=True)
        text(37, 276, f"Savings A/c XXXXXXXX{account_hint}")
        text(457, 276, indian_grouping(closing_balance), right=True)
        text(494, 276, "Registered")
        text(37, 290, "Total")
        text(457, 290, indian_grouping(closing_balance), right=True)
        return 325.0

    def table_header(y: float) -> float:
        text(37, y, title)
        y += 22
        text(37, y, "DATE", bold=True)
        text(X_MODE_HEADER, y, "MODE", bold=True)
        text(X_PARTICULARS, y, "PARTICULARS", bold=True)
        text(X_DEPOSITS, y, "DEPOSITS", bold=True, right=True)
        text(X_WITHDRAWALS, y, "WITHDRAWALS", bold=True, right=True)
        text(X_BALANCE, y, "BALANCE", bold=True, right=True)
        return y + 14

    balance = opening
    for row in rows:
        if row.balance:
            balance = Decimal(row.balance.replace(",", ""))
    closing_balance = balance

    page = 1
    page_deposits = page_withdrawals = Decimal("0.00")
    last_balance = opening

    def page_total(y: float) -> None:
        text(141, y, "Total:")
        text(X_DEPOSITS, y, indian_grouping(page_deposits), right=True)
        printed = page_withdrawals + misprint_withdrawal_total
        text(X_WITHDRAWALS, y, indian_grouping(printed), right=True)
        text(X_BALANCE, y, indian_grouping(last_balance), right=True)
        text(469, 790, f"Page {page}")

    y = table_header(first_page_header())
    text(X_DATE, y, period[0].strftime(DATE_FMT))
    text(X_PARTICULARS, y, "B/F")
    text(X_BALANCE, y, indian_grouping(opening), right=True)
    y += LINE + SINGLE_ROW_PAD

    for row in rows:
        lines = wrap(row.particulars)
        row_height = LINE * len(lines) + (SINGLE_ROW_PAD if len(lines) == 1 else 0)
        if top(y + row_height) < BOTTOM:
            page_total(y + 3)
            canvas.showPage()
            page += 1
            page_deposits = page_withdrawals = Decimal("0.00")
            y = table_header(92.0)
        middle = y + LINE * (len(lines) - 1) / 2
        for index, line in enumerate(lines):
            text(X_PARTICULARS, y + LINE * index, line)
        date_text = row.date.strftime(DATE_FMT)
        text(X_DATE, middle, date_text)
        if row.mode:
            # Right after the date, as in the real statement: the text layer fuses the two.
            text(X_DATE + stringWidth(date_text, FONT, SIZE) + 0.5, middle, row.mode)
        if row.deposit:
            text(X_DEPOSITS, middle, row.deposit, right=True)
            page_deposits += Decimal(row.deposit.replace(",", ""))
        if row.withdrawal:
            text(X_WITHDRAWALS, middle, row.withdrawal, right=True)
            page_withdrawals += Decimal(row.withdrawal.replace(",", ""))
        if row.balance:
            text(X_BALANCE, middle, row.balance, right=True)
            last_balance = Decimal(row.balance.replace(",", ""))
        y += row_height

    page_total(y + 3)
    y += 30
    text(34, y, "Legends Used in Account Statement(s)")
    text(33, y + 12, "Registered Office: ICICI Bank Ltd., ICICI Bank Tower, Sample Road, 000000.")
    canvas.save()

    data = buffer.getvalue()
    return encrypt_pdf(data, encrypted_with) if encrypted_with else data


def _particulars(rng: random.Random, description: str) -> str:
    """The synthetic description, sometimes with an ICICI-style long reference glued on, so
    some cells break a token mid-way."""
    if rng.random() < 0.35:
        return description + "/" + "".join(rng.choice(_ALNUM) for _ in range(rng.randint(36, 60)))
    return description


class IciciSavingsFixtures:
    parser_id = "icici_savings_pdf"

    def build(
        self, seed: int, rows: int, encrypted_with: str | None = None
    ) -> tuple[bytes, ParsedStatement]:
        statement, _ = synthetic_statement(seed, rows, institution="ICICI Bank")
        assert statement.period_start and statement.period_end and statement.account_hint
        assert statement.opening_balance is not None
        rng = random.Random(seed * 7919)  # noqa: S311 (fake data, not crypto)

        printed: list[IciciRow] = []
        expected: list[ParsedTransaction] = []
        for txn in statement.transactions:
            assert txn.balance_after is not None
            amount = indian_grouping(txn.amount)
            row = IciciRow(
                date=txn.date,
                particulars=_particulars(rng, txn.description),
                deposit=amount if txn.direction == "credit" else "",
                withdrawal=amount if txn.direction == "debit" else "",
                balance=indian_grouping(txn.balance_after),
                mode="CMS TRANSACTION" if rng.random() < 0.15 else "",
            )
            printed.append(row)
            expected.append(replace(txn, description=" ".join(wrap(row.particulars)), raw=raw(row)))

        data = render(
            printed,
            opening=statement.opening_balance,
            account_hint=statement.account_hint,
            period=(statement.period_start, statement.period_end),
            encrypted_with=encrypted_with,
        )
        return data, replace(statement, transactions=expected)


def raw(row: IciciRow) -> dict[str, str]:
    """The `raw` cells the parser reports for a row drawn by `render`."""
    out = {"date": row.date.strftime(DATE_FMT), "particulars": " ".join(wrap(row.particulars))}
    if row.mode:
        out["mode"] = row.mode
    for key, value in (
        ("deposits", row.deposit),
        ("withdrawals", row.withdrawal),
        ("balance", row.balance),
    ):
        if value:
            out[key] = value
    return out
