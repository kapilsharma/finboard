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
from finboard.domain.enums import CategoryType
from finboard.domain.errors import ValidationFailed


class BudgetService:
    def __init__(self, uow: UnitOfWork) -> None:
        self.uow = uow

    async def for_month(self, month: date) -> list[Budget]:
        """The limit row in force for each category in that month."""
        return await self.uow.budgets.effective_rows(month.replace(day=1))

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
