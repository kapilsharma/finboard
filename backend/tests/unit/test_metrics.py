"""Metric edge cases (ARCHITECTURE §12, ADR-0017)."""

from decimal import Decimal as D

from finboard.domain.enums import CategoryType as T
from finboard.domain.enums import Direction
from finboard.domain.metrics import (
    METRIC_DEFINITIONS,
    category_limit,
    headline,
    limits_summary,
    pct_change,
    pct_of,
    savings_rate,
    sort_limits,
    totals,
)

DR, CR = Direction.DEBIT, Direction.CREDIT


def test_signed_sums_refunds_reduce_spending_and_transfers_are_left_out() -> None:
    t = totals(
        [
            (T.INCOME, CR, D("1000.00")),
            (T.INCOME, DR, D("100.00")),  # salary reversal
            (T.EXPENSE, DR, D("400.00")),
            (T.EXPENSE, CR, D("50.00")),  # refund into the original category (ADR-0017)
            (T.INVESTMENT, DR, D("200.00")),
            (T.INVESTMENT, CR, D("20.00")),  # redemption
            (T.TRANSFER, DR, D("999.00")),
            (T.TRANSFER, CR, D("999.00")),
        ]
    )
    assert t.income == D("900.00")
    assert t.spending == D("350.00")
    assert t.invested == D("180.00")
    assert t.net_saving == D("550.00")
    assert t.account_net == D("370.00")
    assert t.transfers == D("999.00")


def test_refunds_can_make_a_category_negative() -> None:
    t = totals([(T.EXPENSE, DR, D("100.00")), (T.EXPENSE, CR, D("300.00"))])
    assert t.spending == D("-200.00")


def test_zero_or_negative_income_has_no_savings_rate() -> None:
    assert savings_rate(D("0.00"), D("-50.00")) is None
    assert savings_rate(D("-10.00"), D("-60.00")) is None
    assert savings_rate(D("142702.04"), D("46661.66")) == D("32.7")


def test_percentages_round_once_half_up() -> None:
    assert pct_change(D("142702.04"), D("160791.67")) == D("-11.3")  # -11.2504
    assert pct_change(D("105.00"), D("100.00")) == D("5.0")
    assert pct_change(D("1.00"), D("0.00")) is None
    assert pct_change(D("1.00"), None) is None
    assert pct_of(D("15000.00"), D("46661.66")) == D("32.1")
    assert pct_of(D("100.00"), D("0.00")) is None
    assert pct_of(D("100.00"), D("-5.00")) is None


def test_change_against_a_negative_previous_month_keeps_its_sign_meaningful() -> None:
    # Net saving -100 -> +100 is an improvement: +200 %, not -200 %.
    assert pct_change(D("100.00"), D("-100.00")) == D("200.0")


def test_headline_without_a_previous_month() -> None:
    h = headline(totals([(T.INCOME, CR, D("100.00")), (T.EXPENSE, DR, D("40.00"))]), None)
    assert h.savings_rate == D("60.0")
    assert h.prev_income is None and h.income_delta_pct is None
    assert h.net_saving_delta is None and h.savings_rate_delta_pts is None


def test_headline_against_the_previous_month() -> None:
    prev = totals([(T.INCOME, CR, D("200.00")), (T.EXPENSE, DR, D("50.00"))])
    cur = totals([(T.INCOME, CR, D("100.00")), (T.EXPENSE, DR, D("60.00"))])
    h = headline(cur, prev)
    assert h.income_delta_pct == D("-50.0")
    assert h.spending_delta_pct == D("20.0")
    assert h.net_saving_delta == D("-110.00")
    assert h.savings_rate_delta_pts == D("-35.0")  # 40 % vs 75 %


def test_category_limits_status_and_sort() -> None:
    over = category_limit(D("4093.94"), D("4000.00"))
    exact = category_limit(D("32000.00"), D("32000.00"))
    under = category_limit(D("633.41"), D("2000.00"))
    none = category_limit(D("6850.00"), None)
    zero_limit = category_limit(D("10.00"), D("0.00"))
    assert over.status == "over" and over.remaining == D("-93.94")
    assert exact.status == "under" and exact.remaining == D("0.00")  # ₹0 left is not over
    assert under.pct_used == D("31.7")
    assert none.status == "no_limit" and none.remaining is None and none.pct_used is None
    assert zero_limit.status == "over" and zero_limit.pct_used is None
    ordered = sort_limits(
        [("under", under), ("none", none), ("exact", exact), ("over", over), ("zero", zero_limit)]
    )
    assert [name for name, _ in ordered] == ["zero", "over", "exact", "under", "none"]


def test_limits_summary_left_is_limits_minus_spent() -> None:
    summary = limits_summary(
        [
            category_limit(D("4093.94"), D("4000.00")),
            category_limit(D("500.00"), D("1000.00")),
            category_limit(D("9999.00"), None),  # no limit: not in the summary
        ]
    )
    assert summary is not None
    assert summary.spent_in_limits == D("4593.94") and summary.limits_total == D("5000.00")
    assert summary.left == D("406.06") and summary.over_count == 1
    assert limits_summary([category_limit(D("1.00"), None)]) is None


def test_every_definition_has_label_formula_and_tooltip() -> None:
    for key in ("income", "spending", "invested", "net_saving", "savings_rate", "account_net"):
        d = METRIC_DEFINITIONS[key]
        assert d.label and d.formula and d.tooltip
