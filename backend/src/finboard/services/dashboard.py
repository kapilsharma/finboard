"""The dashboard (ARCHITECTURE §10, §12): grouped SQL in, metrics out.

This module only runs the grouped query and arranges the sums; every formula lives in
`domain/metrics.py`. One query covers the cash-flow trail and the previous month.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from finboard.db.models import Account, Category
from finboard.db.repos import GroupedSum
from finboard.db.uow import UnitOfWork
from finboard.domain import metrics
from finboard.domain.enums import CategoryType
from finboard.domain.errors import ValidationFailed
from finboard.services.budgets import limits_for_month

MAX_TRAIL = 36


def month_start(value: date) -> date:
    return value.replace(day=1)


def add_months(value: date, months: int) -> date:
    index = value.year * 12 + value.month - 1 + months
    return date(index // 12, index % 12 + 1, 1)


def month_end(value: date) -> date:
    return add_months(value, 1) - timedelta(days=1)


def parse_month(text: str) -> date:
    try:
        year, month = (int(part) for part in text.split("-"))
        return date(year, month, 1)
    except ValueError:
        raise ValidationFailed("month must look like 2026-09") from None


@dataclass(frozen=True, slots=True)
class CashflowMonth:
    month: date
    totals: metrics.Totals


@dataclass(frozen=True, slots=True)
class CategoryRow:
    category: Category
    limit: metrics.CategoryLimit


@dataclass(frozen=True, slots=True)
class IncomeSource:
    category: Category
    amount: Decimal
    prev_amount: Decimal | None


@dataclass(frozen=True, slots=True)
class AccountRow:
    account: Account
    totals: metrics.Totals


@dataclass(frozen=True, slots=True)
class DashboardView:
    month: date
    prev_month: date | None
    headline: metrics.Headline
    biggest_spend: tuple[Category, Decimal] | None
    review_count: int
    cashflow: list[CashflowMonth]
    categories: list[CategoryRow]
    limits: metrics.LimitsSummary | None
    income_sources: list[IncomeSource]
    accounts: list[AccountRow]


class DashboardService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def data_version(self) -> int:
        user = await self.uow.users.get(self.uow.user_id)
        return user.data_version if user else 0

    async def months(self) -> list[date]:
        return await self.uow.dashboard.months()

    async def view(self, month: date | None, *, trail: int = 12) -> DashboardView | None:
        """None when the user has no transactions yet. Without a month: the latest one."""
        if not 1 <= trail <= MAX_TRAIL:
            raise ValidationFailed(f"trail must be between 1 and {MAX_TRAIL} months")
        months = await self.uow.dashboard.months()
        if not months:
            return None
        month = month_start(month) if month else months[0]
        prev = add_months(month, -1)
        prev_month = prev if prev in months else None

        first = min(add_months(month, -(trail - 1)), prev)
        rows = await self.uow.dashboard.grouped_sums(first, month_end(month))
        by_month: dict[date, list[GroupedSum]] = defaultdict(list)
        for row in rows:
            by_month[row.month].append(row)

        def totals_for(m: date, rows_: list[GroupedSum] | None = None) -> metrics.Totals:
            source = by_month.get(m, []) if rows_ is None else rows_
            return metrics.totals((r.type, r.direction, r.amount) for r in source)

        current = totals_for(month)
        previous = totals_for(prev) if prev_month else None
        headline = metrics.headline(current, previous)

        categories = {c.id: c for c in await self.uow.categories.list()}
        accounts = {a.id: a for a in await self.uow.accounts.list()}
        spent = _by_category(by_month.get(month, []), CategoryType.EXPENSE)
        limits = await limits_for_month(self.uow, month)
        category_rows = [
            CategoryRow(
                categories[cid],
                metrics.category_limit(spent.get(cid, metrics.ZERO), limits.get(cid)),
            )
            for cid in {*spent, *(c for c, lim in limits.items() if lim is not None)}
            if cid in categories
            and categories[cid].type is CategoryType.EXPENSE
            and (spent.get(cid, metrics.ZERO) != 0 or limits.get(cid) is not None)
        ]
        ordered = metrics.sort_limits([(r.category, r.limit) for r in category_rows])
        biggest = max(
            ((categories[c], v) for c, v in spent.items() if c in categories and v > 0),
            key=lambda item: item[1],
            default=None,
        )

        income = _by_category(by_month.get(month, []), CategoryType.INCOME)
        prev_income = (
            _by_category(by_month.get(prev, []), CategoryType.INCOME) if prev_month else None
        )
        sources = sorted(
            (
                IncomeSource(
                    categories[cid],
                    amount,
                    prev_income.get(cid, metrics.ZERO) if prev_income is not None else None,
                )
                for cid, amount in income.items()
                if cid in categories and amount != 0
            ),
            key=lambda s: (-s.amount, s.category.name.lower()),
        )

        per_account: dict[uuid.UUID, list[GroupedSum]] = defaultdict(list)
        for row in by_month.get(month, []):
            per_account[row.account_id].append(row)
        account_rows = sorted(
            (
                AccountRow(accounts[aid], totals_for(month, account_rows_))
                for aid, account_rows_ in per_account.items()
                if aid in accounts
            ),
            key=lambda r: r.account.name.lower(),
        )

        data_months = [m for m in months if first <= m <= month]
        start = max(add_months(month, -(trail - 1)), min(data_months))
        cashflow = []
        cursor = start
        while cursor <= month:
            cashflow.append(CashflowMonth(cursor, totals_for(cursor)))
            cursor = add_months(cursor, 1)

        return DashboardView(
            month=month,
            prev_month=prev_month,
            headline=headline,
            biggest_spend=biggest,
            review_count=await self.uow.dashboard.review_count(month, month_end(month)),
            cashflow=cashflow,
            categories=[CategoryRow(c, lim) for c, lim in ordered],
            limits=metrics.limits_summary(r.limit for r in category_rows),
            income_sources=sources,
            accounts=account_rows,
        )


def _by_category(rows: list[GroupedSum], type_: CategoryType) -> dict[uuid.UUID, Decimal]:
    """Signed per-category sums of one type."""
    result: dict[uuid.UUID, Decimal] = defaultdict(lambda: metrics.ZERO)
    for row in rows:
        if row.type is type_:
            result[row.category_id] += metrics.signed(row.type, row.direction, row.amount)
    return dict(result)
