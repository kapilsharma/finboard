"""Monthly category limits (ARCHITECTURE §5). The full Settings > Budgets UI arrives in M5.

A limit applies from `effective_from` (the 1st of a month) until the next change; `None` means
"no limit from this month on". Changing a limit never rewrites earlier months.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from finboard.db.models import Budget
from finboard.db.uow import UnitOfWork
from finboard.domain.budgets import BudgetEntry, effective_entries, effective_limits
from finboard.domain.enums import CategoryType
from finboard.domain.errors import NotFound, ValidationFailed


def entry(budget: Budget) -> BudgetEntry:
    return BudgetEntry(budget.category_id, budget.effective_from, budget.monthly_limit)


async def limits_for_month(uow: UnitOfWork, month: date) -> dict[uuid.UUID, Decimal | None]:
    return effective_limits([entry(b) for b in await uow.budgets.history()], month)


class BudgetService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def for_month(self, month: date) -> list[Budget]:
        """The limit row in force for each category in that month."""
        rows = await self.uow.budgets.history()
        by_key = {(b.category_id, b.effective_from): b for b in rows}
        chosen = effective_entries([entry(b) for b in rows], month)
        return [by_key[(e.category_id, e.effective_from)] for e in chosen.values()]

    async def history(self, category_id: uuid.UUID | None = None) -> list[Budget]:
        return await self.uow.budgets.history(category_id)

    async def remove_change(self, category_id: uuid.UUID, effective_from: date) -> None:
        """Undo one limit change; the previous one applies again from that month."""
        if not await self.uow.budgets.delete_entry(category_id, effective_from):
            raise NotFound("No limit change for that category and month")
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.commit()

    async def put(
        self, category_id: uuid.UUID, *, effective_from: date, monthly_limit: Decimal | None
    ) -> Budget:
        if effective_from.day != 1:
            raise ValidationFailed("effective_from must be the first day of a month")
        category = await self.uow.categories.get(category_id)
        if category is None:
            raise ValidationFailed("Unknown category")
        if category.type is not CategoryType.EXPENSE:
            raise ValidationFailed("Only expense categories can have a monthly limit")
        budget = await self.uow.budgets.put(category_id, effective_from, monthly_limit)
        await self.uow.users.bump_data_version(self.uow.user_id)
        await self.uow.commit()
        return budget
