"""User B's dashboard, transaction list and budgets never include or touch user A's data."""

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.uow import unit_of_work
from finboard.services.demo import load_demo

from ..categorisation_helpers import API, category_id

BOB = {"X-Test-User": "bob"}


@pytest.fixture(autouse=True)
async def _alice_has_data(sessionmaker: async_sessionmaker[AsyncSession], alice: Principal) -> None:
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        await load_demo(uow)


async def test_bob_sees_an_empty_finboard(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{API}/dashboard", headers=BOB)).json() is None
    assert (await client.get(f"{API}/dashboard/months", headers=BOB)).json()["months"] == []
    listed = (await client.get(f"{API}/transactions", headers=BOB)).json()
    assert listed["total"] == 0 and listed["items"] == []
    budgets = (await client.get(f"{API}/budgets", params={"month": "2026-09"}, headers=BOB)).json()
    assert budgets["items"] == []
    # Alice's own view is intact.
    assert (await client.get(f"{API}/dashboard")).json()["month"] == "2026-09"


async def test_bob_cannot_filter_by_or_budget_alices_ids(client: httpx.AsyncClient) -> None:
    alices_account = (await client.get(f"{API}/accounts")).json()["items"][0]["id"]
    alices_rent = await category_id(client, "Rent")
    by_account = await client.get(
        f"{API}/transactions", params={"account_id": alices_account}, headers=BOB
    )
    assert by_account.json()["total"] == 0
    by_category = await client.get(
        f"{API}/transactions", params={"category_id": alices_rent}, headers=BOB
    )
    assert by_category.json()["total"] == 0
    put = await client.put(
        f"{API}/budgets/{alices_rent}",
        json={"effective_from": "2026-09", "monthly_limit": "1.00"},
        headers=BOB,
    )
    assert put.status_code == 422
    rent = next(
        i
        for i in (await client.get(f"{API}/dashboard")).json()["categories"]["items"]
        if i["category"]["id"] == alices_rent
    )
    assert rent["limit"] == "32000.00"


async def test_rls_hides_budgets(app_engine: AsyncEngine, alice: Principal, bob: Principal) -> None:
    for user, expected in ((alice, 10), (bob, 0)):
        async with app_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.user_id)}
            )
            assert (
                await conn.execute(text("SELECT count(*) FROM budget"))
            ).scalar_one() == expected
