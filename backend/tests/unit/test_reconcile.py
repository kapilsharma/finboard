from decimal import Decimal as D

from finboard.domain.reconcile import ReconRow, reconcile


def rows(*specs: tuple[str, str, str | None]) -> list[ReconRow]:
    return [
        ReconRow(i, direction, D(amount), None if bal is None else D(bal))
        for i, (direction, amount, bal) in enumerate(specs)
    ]


def test_asset_ok() -> None:
    result = reconcile(
        "asset",
        D("1000.00"),
        D("1150.00"),
        rows(("debit", "100.00", "900.00"), ("credit", "250.00", "1150.00")),
    )
    assert result.status == "ok"
    assert (result.credits, result.debits) == (D("250.00"), D("100.00"))
    assert result.expected_closing == D("1150.00")
    assert result.diff == D("0.00")
    assert result.first_break_seq is None


def test_liability_ok_credit_card() -> None:
    # Owed 5,000; spent 1,200; paid 5,000 → owe 1,200.
    result = reconcile(
        "liability",
        D("5000.00"),
        D("1200.00"),
        rows(("debit", "1200.00", None), ("credit", "5000.00", None)),
    )
    assert result.status == "ok"
    assert result.expected_closing == D("1200.00")


def test_liability_with_asset_formula_would_fail() -> None:
    result = reconcile(
        "asset",
        D("5000.00"),
        D("1200.00"),
        rows(("debit", "1200.00", None), ("credit", "5000.00", None)),
    )
    assert result.status == "mismatch"
    assert result.diff == D("-7600.00")


def test_mismatch_reports_diff() -> None:
    result = reconcile("asset", D("100.00"), D("50.00"), rows(("debit", "40.00", None)))
    assert result.status == "mismatch"
    assert result.expected_closing == D("60.00")
    assert result.diff == D("-10.00")


def test_first_break_seq_points_at_misparsed_row() -> None:
    result = reconcile(
        "asset",
        D("1000.00"),
        D("700.00"),
        rows(
            ("debit", "100.00", "900.00"),
            ("debit", "100.00", "700.00"),  # printed balance says 200 left the account
            ("credit", "0.01", "700.01"),
        ),
    )
    assert result.status == "mismatch"
    assert result.first_break_seq == 1


def test_running_break_even_when_totals_agree() -> None:
    # Totals reconcile but the balances say two rows were swapped in direction.
    result = reconcile(
        "asset",
        D("100.00"),
        D("100.00"),
        rows(("debit", "10.00", "110.00"), ("credit", "10.00", "100.00")),
    )
    assert result.status == "mismatch"
    assert result.first_break_seq == 0


def test_missing_balances_are_unverifiable() -> None:
    assert (
        reconcile("asset", None, D("1.00"), rows(("debit", "1.00", None))).status == "unverifiable"
    )
    assert reconcile("asset", D("1.00"), None, []).status == "unverifiable"


def test_running_balance_without_opening_anchors_on_first_row() -> None:
    ok = reconcile(
        "asset", None, None, rows(("debit", "10.00", "90.00"), ("debit", "5.00", "85.00"))
    )
    assert ok.status == "unverifiable" and ok.first_break_seq is None
    broken = reconcile(
        "asset", None, None, rows(("debit", "10.00", "90.00"), ("debit", "5.00", "80.00"))
    )
    assert broken.status == "mismatch" and broken.first_break_seq == 1


def test_empty_statement_reconciles_when_balances_equal() -> None:
    assert reconcile("asset", D("5.00"), D("5.00"), []).status == "ok"
