"""TEMPLATE fixture builder: draws the Example Bank layout with fake data (reportlab).

Copy it along with parser.py. Reproduce the bank's *layout* only (positions, labels, number and
date formats); all values come from `synthetic_statement`, never from a real statement.
"""

from __future__ import annotations

import io
from dataclasses import replace

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from finboard.parsers.sdk import ParsedStatement, ParsedTransaction
from finboard.parsers.sdk.testing import encrypt_pdf, indian_grouping, synthetic_statement

FMT = "%d/%m/%Y"


class ExampleBankFixtures:
    parser_id = "example_bank_savings_pdf"

    def build(
        self, seed: int, rows: int, encrypted_with: str | None = None
    ) -> tuple[bytes, ParsedStatement]:
        statement, _ = synthetic_statement(seed, rows, institution="Example Bank")
        assert statement.period_start and statement.period_end
        assert statement.opening_balance is not None and statement.closing_balance is not None

        buffer = io.BytesIO()
        canvas = Canvas(buffer, pagesize=A4, invariant=1)
        _, height = A4
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(40, height - 50, "EXAMPLE BANK")
        canvas.setFont("Helvetica", 8)
        canvas.drawString(40, height - 64, "Savings Account Statement")
        canvas.drawString(40, height - 76, f"A/c No: XXXXXX{statement.account_hint}")
        canvas.drawString(
            40,
            height - 88,
            f"From {statement.period_start.strftime(FMT)} To {statement.period_end.strftime(FMT)}",
        )
        canvas.drawString(
            40, height - 100, f"Opening Balance {indian_grouping(statement.opening_balance)}"
        )

        y = height - 124
        canvas.setFont("Helvetica", 7)
        expected: list[ParsedTransaction] = []
        for txn in statement.transactions:
            if y < 60:
                canvas.showPage()
                canvas.setFont("Helvetica", 7)
                y = height - 50
            assert txn.balance_after is not None
            raw = {
                "date": txn.date.strftime(FMT),
                "narration": txn.description,
                "withdrawal": indian_grouping(txn.amount) if txn.direction == "debit" else "0.00",
                "deposit": indian_grouping(txn.amount) if txn.direction == "credit" else "0.00",
                "balance": indian_grouping(txn.balance_after),
            }
            canvas.drawString(40, y, raw["date"])
            canvas.drawString(90, y, raw["narration"])
            canvas.drawRightString(440, y, raw["withdrawal"])
            canvas.drawRightString(495, y, raw["deposit"])
            canvas.drawRightString(555, y, raw["balance"])
            expected.append(replace(txn, raw=raw))
            y -= 11

        canvas.setFont("Helvetica", 8)
        canvas.drawString(
            40, max(y - 12, 40), f"Closing Balance {indian_grouping(statement.closing_balance)}"
        )
        canvas.save()

        data = buffer.getvalue()
        if encrypted_with:
            data = encrypt_pdf(data, encrypted_with)
        return data, replace(statement, transactions=expected)
