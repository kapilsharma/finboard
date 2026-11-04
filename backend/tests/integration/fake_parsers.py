"""Test-only adapters, loaded through FINBOARD_EXTRA_PARSERS (see tests/conftest.py).

Each recognises a PDF containing its marker text, made by `marker_pdf()`:
  MISMATCH-FIXTURE  a statement whose closing balance is off by 10.00
  SOFT-TIMEOUT      raises Celery's SoftTimeLimitExceeded, as the soft time limit would
  HANG-FIXTURE      never returns and ignores the soft limit (needs the hard kill)
"""

from __future__ import annotations

import io
import time
from datetime import date
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field
from reportlab.pdfgen.canvas import Canvas

from finboard.parsers.sdk import (
    PARSER_API_VERSION,
    OpenedDocument,
    ParsedStatement,
    ParsedTransaction,
)


def marker_pdf(marker: str) -> bytes:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, invariant=1)
    canvas.drawString(72, 720, marker)
    canvas.save()
    return buffer.getvalue()


class _Marker:
    marker = ""
    version = "1.0.0"
    api_version = PARSER_API_VERSION
    institutions: tuple[str, ...] = ("Test Bank",)
    account_types: tuple[str, ...] = ("savings",)
    file_types = (".pdf",)
    options_schema = None

    def detect(self, doc: OpenedDocument) -> float:
        assert doc.pdf is not None
        return 0.99 if self.marker in doc.pdf.page_text(0) else 0.0


class MismatchParser(_Marker):
    id = "test_mismatch"
    name = "Test: mismatching statement"
    marker = "MISMATCH-FIXTURE"

    def parse(self, doc: OpenedDocument, options: Any) -> ParsedStatement:
        return ParsedStatement(
            institution="Test Bank",
            balance_kind="asset",
            account_hint="4242",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            opening_balance=Decimal("1000.00"),
            closing_balance=Decimal("900.00"),  # should be 890.00
            transactions=[
                ParsedTransaction(date(2026, 9, 2), "COFFEE", Decimal("60.00"), "debit"),
                ParsedTransaction(date(2026, 9, 3), "LUNCH", Decimal("50.00"), "debit"),
            ],
        )


class SoftTimeoutParser(_Marker):
    id = "test_soft_timeout"
    name = "Test: soft time limit"
    marker = "SOFT-TIMEOUT"

    def parse(self, doc: OpenedDocument, options: Any) -> ParsedStatement:
        from celery.exceptions import SoftTimeLimitExceeded

        raise SoftTimeLimitExceeded()


class HangingParser(_Marker):
    id = "test_hang"
    name = "Test: hangs forever"
    marker = "HANG-FIXTURE"

    def parse(self, doc: OpenedDocument, options: Any) -> ParsedStatement:
        # Like a parser stuck in C code: it swallows the soft limit, so only the hard kill
        # (time_limit, prefork pool) can stop it.
        while True:
            try:
                time.sleep(0.05)
            except BaseException:  # noqa: S112
                continue


class OptionsParser(_Marker):
    """Has options: proves a user's saved options reach `parse()`."""

    id = "test_options"
    name = "Test: parser with options"
    marker = "OPTIONS-FIXTURE"

    class Options(BaseModel):
        institution_label: str = Field(default="Options Bank", max_length=40)
        skip_zero_rows: bool = True

    options_schema = Options

    def parse(self, doc: OpenedDocument, options: Any) -> ParsedStatement:
        assert isinstance(options, self.Options)
        return ParsedStatement(
            institution=options.institution_label,
            balance_kind="asset",
            account_hint="7777",
            period_start=date(2026, 9, 1),
            period_end=date(2026, 9, 30),
            opening_balance=Decimal("100.00"),
            closing_balance=Decimal("90.00"),
            transactions=[
                ParsedTransaction(
                    date=date(2026, 9, 2),
                    value_date=None,
                    description="OPTIONS TEST ROW",
                    amount=Decimal("10.00"),
                    direction="debit",
                    balance_after=Decimal("90.00"),
                    raw={},
                )
            ],
            warnings=[],
        )
