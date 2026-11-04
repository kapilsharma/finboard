"""Metric definitions: the single source of truth for every dashboard number (ARCHITECTURE §12).

Pure functions over grouped sums. `services/dashboard.py` runs the grouped SQL and hands the
sums here; `GET /meta` serves `METRIC_DEFINITIONS`, which the UI shows verbatim as tooltips.

Amounts are positive with a direction (ADR-0008); each metric is a *signed* sum per category
type (ADR-0017), so a refund categorised into Shopping reduces Shopping. Transfers are left out
everywhere. Months are calendar months of the transaction date.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from finboard.domain.enums import CategoryType, Direction

ZERO = Decimal("0.00")
_PCT = Decimal("0.1")  # one rounding, to what the UI shows (32.7 %, −10.2 pts)

BudgetStatus = Literal["under", "over", "no_limit"]


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    label: str
    formula: str
    tooltip: str


METRIC_DEFINITIONS: dict[str, MetricDefinition] = {
    "month": MetricDefinition(
        "Month",
        "Calendar month of the transaction date",
        "Transactions count in the calendar month of their date, not the statement period.",
    ),
    "income": MetricDefinition(
        "Income",
        "Σ income credits − Σ income debits",
        "Money in that is categorised as income. Transfers between your accounts are left out.",
    ),
    "spending": MetricDefinition(
        "Spending",
        "Σ expense debits − Σ expense credits",
        "Money out that is categorised as an expense. A refund in the same category reduces it.",
    ),
    "invested": MetricDefinition(
        "Invested",
        "Σ investment debits − Σ investment credits",
        "Money put into SIPs, mutual funds and deposits, less anything taken out.",
    ),
    "net_saving": MetricDefinition(
        "Net saving",
        "Income − Spending",
        "What was left of your income after spending. Investments come out of this.",
    ),
    "savings_rate": MetricDefinition(
        "Savings rate",
        "Net saving ÷ Income × 100 (none if Income ≤ 0)",
        "The share of your income you didn't spend.",
    ),
    "invested_pct_of_net_saving": MetricDefinition(
        "Invested, % of net saving",
        "Invested ÷ Net saving × 100 (none if Net saving ≤ 0)",
        "How much of what you saved went into investments.",
    ),
    "delta_pct": MetricDefinition(
        "Change",
        "(this month − previous month) ÷ previous month × 100 (none if previous is 0)",
        "Income up is good; spending up is bad.",
    ),
    "account_net": MetricDefinition(
        "Account net",
        "Income − Spending − Invested for the account",
        "What one account gained or lost in the month. Transfers are left out.",
    ),
    "category_remaining": MetricDefinition(
        "Remaining",
        "Limit − Spent for the category and month",
        "Money left in a category's monthly limit; over the limit when negative.",
    ),
    "limits_summary": MetricDefinition(
        "Limits",
        "Over categories with a limit: Σ spent, Σ limit, left = Σ limit − Σ spent",
        "Spending in categories that have a limit, against the sum of those limits.",
    ),
    "review_count": MetricDefinition(
        "Needs review",
        "Transactions in the month that still need a category",
        "Categorise them so the numbers are complete.",
    ),
}


# ---------------------------------------------------------------- sums


@dataclass(slots=True)
class Totals:
    """Signed totals of one group of transactions (a month, an account, …)."""

    income: Decimal = ZERO
    spending: Decimal = ZERO
    invested: Decimal = ZERO
    transfers: Decimal = ZERO  # moved between own accounts (debits); shown, never counted

    def add(self, type_: CategoryType, direction: Direction, amount: Decimal) -> None:
        credit = direction is Direction.CREDIT
        match type_:
            case CategoryType.INCOME:
                self.income += amount if credit else -amount
            case CategoryType.EXPENSE:
                self.spending += -amount if credit else amount
            case CategoryType.INVESTMENT:
                self.invested += -amount if credit else amount
            case CategoryType.TRANSFER:
                if not credit:
                    self.transfers += amount

    @property
    def net_saving(self) -> Decimal:
        return self.income - self.spending

    @property
    def account_net(self) -> Decimal:
        return self.income - self.spending - self.invested


def signed(type_: CategoryType, direction: Direction, amount: Decimal) -> Decimal:
    """A transaction's contribution to its type's metric (0 for transfers)."""
    credit = direction is Direction.CREDIT
    if type_ is CategoryType.INCOME:
        return amount if credit else -amount
    if type_ in (CategoryType.EXPENSE, CategoryType.INVESTMENT):
        return -amount if credit else amount
    return ZERO


def totals(rows: Iterable[tuple[CategoryType, Direction, Decimal]]) -> Totals:
    result = Totals()
    for type_, direction, amount in rows:
        result.add(type_, direction, amount)
    return result


# ---------------------------------------------------------------- ratios


def _round(value: Decimal) -> Decimal:
    return value.quantize(_PCT, rounding=ROUND_HALF_UP)


def savings_rate(income: Decimal, net_saving: Decimal) -> Decimal | None:
    """Net saving ÷ Income × 100; None if Income ≤ 0."""
    if income <= 0:
        return None
    return _round(net_saving / income * 100)


def pct_of(part: Decimal, whole: Decimal) -> Decimal | None:
    """part ÷ whole × 100; None if whole ≤ 0 (e.g. invested % of net saving)."""
    if whole <= 0:
        return None
    return _round(part / whole * 100)


def pct_change(this: Decimal, prev: Decimal | None) -> Decimal | None:
    """(this − prev) ÷ prev × 100; None if prev is missing or 0."""
    if prev is None or prev == 0:
        return None
    return _round((this - prev) / abs(prev) * 100)


def points_change(this: Decimal | None, prev: Decimal | None) -> Decimal | None:
    """Difference of two percentages in percentage points."""
    if this is None or prev is None:
        return None
    return _round(this - prev)


# ---------------------------------------------------------------- limits


@dataclass(frozen=True, slots=True)
class CategoryLimit:
    spent: Decimal
    limit: Decimal | None
    remaining: Decimal | None
    pct_used: Decimal | None
    status: BudgetStatus


def category_limit(spent: Decimal, limit: Decimal | None) -> CategoryLimit:
    """Remaining = Limit − Spent: `over` when negative, `under` otherwise, `no_limit` without a
    limit. With a limit of 0, any spending is over and `pct_used` is None (it sorts first)."""
    if limit is None:
        return CategoryLimit(spent, None, None, None, "no_limit")
    remaining = limit - spent
    used = _round(spent / limit * 100) if limit > 0 else (Decimal(100) if spent <= 0 else None)
    return CategoryLimit(spent, limit, remaining, used, "over" if remaining < 0 else "under")


def sort_limits[T](items: Sequence[tuple[T, CategoryLimit]]) -> list[tuple[T, CategoryLimit]]:
    """`pct_used` descending (over-limit first); `no_limit` last, by spent descending."""

    def key(item: tuple[T, CategoryLimit]) -> tuple[int, Decimal, Decimal]:
        status = item[1]
        if status.limit is None:
            return (1, Decimal(0), -status.spent)
        used = status.pct_used if status.pct_used is not None else Decimal("1e9")
        return (0, -used, -status.spent)

    return sorted(items, key=key)


@dataclass(frozen=True, slots=True)
class LimitsSummary:
    spent_in_limits: Decimal
    limits_total: Decimal
    left: Decimal  # negative = over in total
    over_count: int


def limits_summary(items: Iterable[CategoryLimit]) -> LimitsSummary | None:
    """Over the categories that have a limit. None when no category has one."""
    limited = [i for i in items if i.limit is not None]
    if not limited:
        return None
    spent = sum((i.spent for i in limited), ZERO)
    total = sum((i.limit for i in limited if i.limit is not None), ZERO)
    return LimitsSummary(spent, total, total - spent, sum(1 for i in limited if i.status == "over"))


# ---------------------------------------------------------------- month comparison


@dataclass(frozen=True, slots=True)
class Headline:
    income: Decimal
    spending: Decimal
    net_saving: Decimal
    savings_rate: Decimal | None
    invested: Decimal
    invested_pct_of_net_saving: Decimal | None
    prev_income: Decimal | None = None
    prev_spending: Decimal | None = None
    prev_net_saving: Decimal | None = None
    prev_savings_rate: Decimal | None = None
    income_delta_pct: Decimal | None = None
    spending_delta_pct: Decimal | None = None
    net_saving_delta: Decimal | None = None
    savings_rate_delta_pts: Decimal | None = None


def headline(current: Totals, previous: Totals | None) -> Headline:
    rate = savings_rate(current.income, current.net_saving)
    base = Headline(
        income=current.income,
        spending=current.spending,
        net_saving=current.net_saving,
        savings_rate=rate,
        invested=current.invested,
        invested_pct_of_net_saving=pct_of(current.invested, current.net_saving),
    )
    if previous is None:
        return base
    prev_rate = savings_rate(previous.income, previous.net_saving)
    return replace(
        base,
        prev_income=previous.income,
        prev_spending=previous.spending,
        prev_net_saving=previous.net_saving,
        prev_savings_rate=prev_rate,
        income_delta_pct=pct_change(current.income, previous.income),
        spending_delta_pct=pct_change(current.spending, previous.spending),
        net_saving_delta=current.net_saving - previous.net_saving,
        savings_rate_delta_pts=points_change(rate, prev_rate),
    )
