"""Budget lookup (ARCHITECTURE §5): a category's limit for month M is the row with the
greatest `effective_from` on or before M. A NULL limit means "no limit from then on", and a
change from month M never alters earlier months."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class BudgetEntry:
    category_id: uuid.UUID
    effective_from: date  # the 1st of a month
    monthly_limit: Decimal | None


def effective_entries(history: Iterable[BudgetEntry], month: date) -> dict[uuid.UUID, BudgetEntry]:
    """The entry in force for each category in `month` (categories without one are absent)."""
    first = month.replace(day=1)
    chosen: dict[uuid.UUID, BudgetEntry] = {}
    for entry in history:
        if entry.effective_from > first:
            continue
        current = chosen.get(entry.category_id)
        if current is None or entry.effective_from > current.effective_from:
            chosen[entry.category_id] = entry
    return chosen


def effective_limits(
    history: Iterable[BudgetEntry], month: date
) -> dict[uuid.UUID, Decimal | None]:
    """category → limit in force for `month` (None = explicitly no limit)."""
    return {cid: e.monthly_limit for cid, e in effective_entries(history, month).items()}
