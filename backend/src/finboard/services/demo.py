"""Demo data: the synthetic sample from the approved design handover (docs/handover/design/),
loaded into one user's (empty) Finboard. Used by `finboard demo-data`, the golden dashboard
test, screenshots and the end-to-end tests. Every value is made up.

The CSV has no direction column: income rows are money in; expense, investment and transfer
rows (the card bill payment from savings) are money out.
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from importlib import resources
from typing import Any

from finboard.categorisation.normalise import normalise
from finboard.db.models import Account, Category
from finboard.db.uow import UnitOfWork
from finboard.domain.enums import AccountType, CategorisedBy, CategoryType, Direction
from finboard.domain.errors import Conflict
from finboard.domain.fingerprint import FINGERPRINT_VERSION

DEMO_PACKAGE = "finboard.seed.demo"
ACCOUNT_TYPES = {"Savings account": AccountType.SAVINGS, "Credit card": AccountType.CREDIT_CARD}


@dataclass(frozen=True, slots=True)
class DemoResult:
    transactions: int
    accounts: int
    budgets: int
    first_month: date
    last_month: date


def _read(name: str) -> list[dict[str, str]]:
    text = resources.files(DEMO_PACKAGE).joinpath(name).read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(text)))


async def load_demo(uow: UnitOfWork) -> DemoResult:
    """Load the sample into the unit of work's user. Refuses if they have transactions."""
    if await uow.dashboard.months():
        raise Conflict("Demo data only goes into an empty Finboard (this one has transactions)")
    rows = _read("sample-transactions.csv")
    budgets = _read("budgets.csv")

    accounts: dict[str, Account] = {a.name: a for a in await uow.accounts.list()}
    for name in sorted({r["account"] for r in rows}):
        if name not in accounts:
            accounts[name] = await uow.accounts.add(
                Account(name=name, type=ACCOUNT_TYPES.get(name, AccountType.OTHER))
            )
    categories: dict[str, Category] = {
        c.name: c for c in await uow.categories.list() if c.parent_id is None
    }
    for row in rows:
        if row["category"] not in categories:
            categories[row["category"]] = await uow.categories.add(
                Category(name=row["category"], type=CategoryType(row["type"]))
            )

    values: list[dict[str, Any]] = []
    for row in rows:
        type_ = CategoryType(row["type"])
        category = categories[row["category"]]
        review = row["needs_review"] == "yes"
        if type_ is CategoryType.TRANSFER:
            by = CategorisedBy.TRANSFER
        elif review:
            by = CategorisedBy.DEFAULT
        else:
            by = CategorisedBy.MANUAL
        values.append(
            {
                "account_id": accounts[row["account"]].id,
                "date": date.fromisoformat(row["date"]),
                "description_raw": row["description"],
                "description_norm": normalise(row["description"]),
                "amount": Decimal(row["amount"]).quantize(Decimal("0.01")),
                "direction": Direction.CREDIT if type_ is CategoryType.INCOME else Direction.DEBIT,
                "category_id": category.id,
                "type": category.type,
                "categorised_by": by,
                "needs_review": review,
                "fingerprint": hashlib.sha256(f"demo|{row['id']}".encode()).hexdigest(),
                "fingerprint_version": FINGERPRINT_VERSION,
                "raw": {"demo_id": row["id"]},
            }
        )
    inserted = await uow.txns.insert_new(values)

    months = sorted({v["date"].replace(day=1) for v in values})
    for row in budgets:
        limited = categories.get(row["category"])
        if limited is not None:
            await uow.budgets.put(limited.id, months[0], Decimal(row["monthly_limit"]))
    await uow.users.bump_data_version(uow.user_id)
    await uow.commit()
    return DemoResult(
        len(inserted), len({r["account"] for r in rows}), len(budgets), months[0], months[-1]
    )
