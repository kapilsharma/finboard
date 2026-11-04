"""Synthetic statements in a generic table layout (reportlab). Test-time only; never commit output.

The seed picks the variant, so the contract suite covers them all:
  seed % 3 == 0  credit card (liability): Date | Transaction Details | Amount (INR), `Cr` marks
                 credits, no running balance
  otherwise      bank account (asset): Date | Description/Narration | Debit/Withdrawal |
                 Credit/Deposit | Balance, two date formats
Long descriptions wrap onto a second line and tables run over several pages.
"""

from __future__ import annotations

import io
from dataclasses import replace

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from finboard.parsers.sdk import ParsedStatement, ParsedTransaction
from finboard.parsers.sdk.testing import encrypt_pdf, indian_grouping, synthetic_statement

INSTITUTION = "Sample Co-operative Bank Ltd"
DESC_WIDTH = 190.0  # points per description line before wrapping
MAX_DESC_WIDTH = 245.0  # x 105 → 350: still clear of the Debit column's values
LINE = 13.0
FONT = "Helvetica"
SIZE = 8


def _wrap(text: str) -> list[str]:
    """Wrap at spaces so no line runs into the amount columns (the parser rejoins with
    a space, so wrapping only at spaces keeps the text exact)."""
    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        candidate = f"{current} {word}" if current else word
        if current and stringWidth(candidate, FONT, SIZE) > DESC_WIDTH:
            lines.append(current)
            current = word
        else:
            current = candidate
    lines.append(current)
    for line in lines:
        assert stringWidth(line, FONT, SIZE) <= MAX_DESC_WIDTH, "description token too long"
    return lines


class GenericTableFixtures:
    parser_id = "generic_table"

    def build(
        self, seed: int, rows: int, encrypted_with: str | None = None
    ) -> tuple[bytes, ParsedStatement]:
        liability = seed % 3 == 0
        statement, _ = synthetic_statement(
            seed,
            rows,
            balance_kind="liability" if liability else "asset",
            institution=INSTITUTION,
            with_running_balance=not liability,
        )
        date_fmt = "%d-%b-%Y" if seed % 2 else "%d/%m/%Y"
        labels = (
            ("Narration", "Withdrawal", "Deposit")
            if seed % 4 == 1
            else (
                "Description",
                "Debit",
                "Credit",
            )
        )

        buffer = io.BytesIO()
        canvas = Canvas(buffer, pagesize=A4, invariant=1)
        canvas.setTitle("Statement")
        width, height = A4
        x_date, x_desc, x_debit, x_credit, x_bal = 40.0, 105.0, 400.0, 475.0, 555.0
        assert statement.period_start and statement.period_end
        assert statement.opening_balance is not None and statement.closing_balance is not None

        def header_block() -> float:
            canvas.setFont("Helvetica-Bold", 13)
            canvas.drawString(40, height - 50, INSTITUTION)
            canvas.setFont(FONT, 9)
            title = "Credit Card Statement" if liability else "Savings Account Statement"
            canvas.drawString(40, height - 66, title)
            label = "Card Number" if liability else "Account Number"
            canvas.drawString(40, height - 80, f"{label}: XXXXXXXX{statement.account_hint}")
            start = statement.period_start.strftime(date_fmt)  # type: ignore[union-attr]
            end = statement.period_end.strftime(date_fmt)  # type: ignore[union-attr]
            canvas.drawString(40, height - 94, f"Statement Period: {start} to {end}")
            opening = indian_grouping(statement.opening_balance)  # type: ignore[arg-type]
            canvas.drawString(40, height - 108, f"Opening Balance: INR {opening}")
            return height - 135

        def table_header(y: float) -> float:
            canvas.setFont("Helvetica-Bold", SIZE)
            canvas.drawString(x_date, y, "Date")
            if liability:
                canvas.drawString(x_desc, y, "Transaction Details")
                canvas.drawRightString(x_bal, y, "Amount (INR)")
            else:
                canvas.drawString(x_desc, y, labels[0])
                canvas.drawRightString(x_debit, y, labels[1])
                canvas.drawRightString(x_credit, y, labels[2])
                canvas.drawRightString(x_bal, y, "Balance")
            canvas.setFont(FONT, SIZE)
            return y - LINE - 2

        page = 1

        def footer() -> None:
            canvas.setFont(FONT, 7)
            canvas.drawCentredString(width / 2, 30, f"Page {page}")

        y = table_header(header_block())
        expected: list[ParsedTransaction] = []
        for txn in statement.transactions:
            lines = _wrap(txn.description)
            if y - LINE * len(lines) < 60:
                footer()
                canvas.showPage()
                page += 1
                y = table_header(height - 50)
            date_text = txn.date.strftime(date_fmt)
            amount_text = indian_grouping(txn.amount)
            raw: dict[str, str] = {"date": date_text, "description": txn.description}
            canvas.drawString(x_date, y, date_text)
            canvas.drawString(x_desc, y, lines[0])
            if liability:
                cell = amount_text + (" Cr" if txn.direction == "credit" else "")
                canvas.drawRightString(x_bal, y, cell)
                raw["amount"] = cell
            else:
                column = x_debit if txn.direction == "debit" else x_credit
                canvas.drawRightString(column, y, amount_text)
                raw[txn.direction] = amount_text
                assert txn.balance_after is not None
                balance_text = indian_grouping(txn.balance_after)
                canvas.drawRightString(x_bal, y, balance_text)
                raw["balance"] = balance_text
            for extra in lines[1:]:
                y -= LINE
                canvas.drawString(x_desc, y, extra)
            y -= LINE + 2
            expected.append(replace(txn, raw=raw))

        if y < 90:
            footer()
            canvas.showPage()
            page += 1
            y = height - 60
        canvas.setFont(FONT, 9)
        closing = indian_grouping(statement.closing_balance)
        canvas.drawString(40, y - 10, f"Closing Balance: INR {closing}")
        canvas.setFont(FONT, 7)
        canvas.drawString(40, y - 30, "This is a computer generated statement.")
        footer()
        canvas.save()

        data = buffer.getvalue()
        if encrypted_with:
            data = encrypt_pdf(data, encrypted_with)
        return data, replace(statement, transactions=expected)
