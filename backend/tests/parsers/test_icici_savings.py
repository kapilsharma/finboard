"""ICICI savings adapter: the edge cases the contract suite's random fixtures may not hit.

All statements are drawn by the adapter's own fixture `render` with made-up values.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from finboard.parsers.builtin.icici_savings_pdf.fixtures import IciciRow, render, wrap
from finboard.parsers.builtin.icici_savings_pdf.parser import IciciSavingsPdfParser
from finboard.parsers.sdk import ParsedStatement, ParserError, open_document

PERIOD = (date(2026, 10, 1), date(2026, 10, 31))
PARSER = IciciSavingsPdfParser()
LONG = (
    "UPI/SAMPLE MERCHANT PRIVATE LIMITED/samplemerchant@okbank/Payment for invoice number "
    "four two/EXAMPLE BANK/123456789012/ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789ABCDEFGHIJKLMN "
    "extra remark words here"
)


def _parse(rows: list[IciciRow], opening: str = "10,000.00", **kwargs: object) -> ParsedStatement:
    data = render(
        rows,
        opening=Decimal(opening.replace(",", "")),
        account_hint="4321",
        period=PERIOD,
        **kwargs,
    )  # type: ignore[arg-type]
    with open_document(data) as doc:
        assert PARSER.detect(doc) >= 0.9
        return PARSER.parse(doc, None)


def test_long_rows_next_to_one_line_rows_keep_their_own_lines() -> None:
    """Rows touch each other; a 5-line row's last line is nearer the next row's date line than
    its own. Grouping by distance would steal it, grouping by symmetry must not."""
    assert len(wrap(LONG)) >= 4
    rows = [
        IciciRow(date(2026, 10, 2), LONG, withdrawal="100.00", balance="9,900.00"),
        IciciRow(date(2026, 10, 2), "SHORT ONE", withdrawal="50.00", balance="9,850.00"),
        IciciRow(date(2026, 10, 3), LONG + " more", deposit="1,000.00", balance="10,850.00"),
        IciciRow(date(2026, 10, 4), "SHORT TWO", withdrawal="10.00", balance="10,840.00"),
    ]
    parsed = _parse(rows)
    assert [t.description for t in parsed.transactions] == [
        " ".join(wrap(r.particulars)) for r in rows
    ]
    assert parsed.warnings == []
    assert parsed.opening_balance == Decimal("10000.00")
    assert parsed.closing_balance == Decimal("10840.00")
    assert (parsed.account_hint, parsed.period_start, parsed.period_end) == ("4321", *PERIOD)


def test_mode_fused_to_the_date_is_kept_out_of_the_description() -> None:
    rows = [
        IciciRow(
            date(2026, 10, 28),
            "ACH/123456789012/SAMPLE_SIP__000111222",
            withdrawal="500.00",
            balance="9,500.00",
            mode="CMS TRANSACTION",
        ),
    ]
    (txn,) = _parse(rows).transactions
    assert txn.date == date(2026, 10, 28)
    assert txn.description == "ACH/123456789012/SAMPLE_SIP__000111222"
    assert txn.raw["mode"] == "CMS TRANSACTION"


def test_reversal_is_a_debit_then_a_credit_with_the_same_reference() -> None:
    ref = "UPI/MERCHANT/m@bank/Payment/BANK/987654321098/XYZ"
    rows = [
        IciciRow(date(2026, 10, 30), ref, withdrawal="5.00", balance="9,995.00"),
        IciciRow(
            date(2026, 10, 31),
            "REV " + ref,
            deposit="5.00",
            balance="10,000.00",
            mode="CMS TRANSACTION",
        ),
    ]
    first, second = _parse(rows).transactions
    assert (first.direction, first.amount) == ("debit", Decimal("5.00"))
    assert (second.direction, second.amount) == ("credit", Decimal("5.00"))
    assert second.balance_after == Decimal("10000.00")


def test_same_day_duplicates_are_two_transactions() -> None:
    row = IciciRow(
        date(2026, 10, 5), "UPI/TEA STALL/tea@bank/tea", withdrawal="20.00", balance="9,980.00"
    )
    twin = IciciRow(row.date, row.particulars, withdrawal="20.00", balance="9,960.00")
    parsed = _parse([row, twin])
    assert len(parsed.transactions) == 2
    assert parsed.transactions[0].description == parsed.transactions[1].description


def test_zero_amount_row_is_skipped_with_a_warning() -> None:
    rows = [
        IciciRow(date(2026, 10, 6), "CHARGES WAIVED", balance="10,000.00"),
        IciciRow(date(2026, 10, 7), "UPI/SHOP/s@bank/x", withdrawal="1.00", balance="9,999.00"),
    ]
    parsed = _parse(rows)
    assert [t.description for t in parsed.transactions] == ["UPI/SHOP/s@bank/x"]
    assert parsed.warnings == ["Skipped a row dated 2026-10-06 with no amount"]


def test_page_total_mismatch_is_reported() -> None:
    rows = [IciciRow(date(2026, 10, 8), "ATM WDL", withdrawal="100.00", balance="9,900.00")]
    parsed = _parse(rows, misprint_withdrawal_total=Decimal("1.00"))
    assert parsed.warnings == ["The withdrawals on page 1 don't add up to the page total"]


def test_row_with_deposit_and_withdrawal_is_an_error() -> None:
    rows = [
        IciciRow(date(2026, 10, 9), "ODD", deposit="1.00", withdrawal="1.00", balance="10,000.00")
    ]
    with pytest.raises(ParserError, match="both a deposit and a withdrawal"):
        _parse(rows)


def test_many_rows_run_over_pages_and_every_page_total_checks_out() -> None:
    balance = Decimal("10000.00")
    rows = []
    for i in range(60):
        balance -= Decimal("1.00")
        rows.append(
            IciciRow(
                date(2026, 10, 1 + i // 2),
                LONG if i % 3 == 0 else f"ROW {i}",
                withdrawal="1.00",
                balance=f"{balance:,.2f}",
            )
        )
    parsed = _parse(rows)
    assert len(parsed.transactions) == 60
    assert parsed.warnings == []
    assert parsed.closing_balance == balance


def test_other_statements_are_refused() -> None:
    from finboard.parsers.builtin.generic_table.fixtures import GenericTableFixtures

    data, _ = GenericTableFixtures().build(1, 5)
    with open_document(data) as doc:
        assert PARSER.detect(doc) == 0.0
        with pytest.raises(ParserError, match="ICICI"):
            PARSER.parse(doc, None)
