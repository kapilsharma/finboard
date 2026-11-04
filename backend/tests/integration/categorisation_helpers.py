"""Helpers for the categorisation tests: committed transactions with chosen descriptions."""

from __future__ import annotations

import secrets
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.categorisation.normalise import normalise
from finboard.db.models import Account
from finboard.db.uow import unit_of_work
from finboard.domain.enums import AccountType, CategorisedBy, Direction

API = "/api/v1"
DAY = date(2026, 9, 10)


async def account(
    sm: async_sessionmaker[AsyncSession],
    user: Principal,
    name: str = "Savings",
    type: AccountType = AccountType.SAVINGS,
) -> uuid.UUID:
    async with unit_of_work(sm, user.user_id) as uow:
        created = await uow.accounts.add(Account(name=name, type=type))
        await uow.commit()
        return created.id


async def add_txns(
    sm: async_sessionmaker[AsyncSession],
    user: Principal,
    account_id: uuid.UUID,
    rows: list[tuple[str, str, str]] | list[tuple[str, str, str, date]],
    *,
    categorised_by: CategorisedBy = CategorisedBy.DEFAULT,
    category_key: str | None = None,
) -> list[uuid.UUID]:
    """rows: (description, amount, direction[, date]). Rows start uncategorised (the fallback
    category, needs_review) unless `category_key`/`categorised_by` say otherwise."""
    async with unit_of_work(sm, user.user_id) as uow:
        fallback = {
            Direction.DEBIT: await uow.categories.by_system_key("uncategorized"),
            Direction.CREDIT: await uow.categories.by_system_key("uncategorized_income"),
        }
        chosen = await uow.categories.by_system_key(category_key) if category_key else None
        values: list[dict[str, Any]] = []
        for row in rows:
            description, amount, direction = row[0], row[1], Direction(row[2])
            when = row[3] if len(row) > 3 else DAY  # type: ignore[misc]
            category = chosen or fallback[direction]
            assert category is not None
            values.append(
                {
                    "account_id": account_id,
                    "date": when,
                    "description_raw": description,
                    "description_norm": normalise(description),
                    "amount": Decimal(amount),
                    "direction": direction,
                    "category_id": category.id,
                    "type": category.type,
                    "categorised_by": categorised_by,
                    "needs_review": categorised_by is CategorisedBy.DEFAULT and chosen is None,
                    "fingerprint": secrets.token_hex(32),
                    "fingerprint_version": 1,
                }
            )
        inserted = await uow.txns.insert_new(values)
        await uow.commit()
        by_fp = {v["fingerprint"]: inserted[v["fingerprint"]] for v in values}
        return [by_fp[v["fingerprint"]] for v in values]


async def category_id(client: httpx.AsyncClient, name: str, **kw: Any) -> str:
    response = await client.get(f"{API}/categories", **kw)
    assert response.status_code == 200
    for item in response.json()["items"]:
        if item["name"] == name:
            return str(item["id"])
    raise AssertionError(f"no category {name!r}")


async def txn(client: httpx.AsyncClient, txn_id: uuid.UUID | str, **kw: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/transactions/{txn_id}", **kw)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def clear_rules(client: httpx.AsyncClient, **kw: Any) -> None:
    """Start from no rules (new users get the starter pack)."""
    response = await client.post(
        f"{API}/rules/import",
        json={"content": "finboard_rule_pack: 1\nrules: []\n", "mode": "replace"},
        **kw,
    )
    assert response.status_code == 200, response.text


async def create_rule(client: httpx.AsyncClient, **body: Any) -> dict[str, Any]:
    body.setdefault("match_kind", "contains")
    response = await client.post(f"{API}/rules", json=body)
    assert response.status_code == 201, response.text
    created: dict[str, Any] = response.json()
    return created
