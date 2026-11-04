"""Dashboard ETag (ARCHITECTURE §10): unchanged data → 304; any financial write changes it."""

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.uow import unit_of_work
from finboard.services.demo import load_demo

from .categorisation_helpers import category_id

API = "/api/v1"


async def etag(client: httpx.AsyncClient, **params: str) -> str:
    response = await client.get(f"{API}/dashboard", params=params)
    assert response.status_code == 200
    return response.headers["etag"]


async def test_unchanged_data_is_304_and_writes_change_the_etag(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        await load_demo(uow)
    first = await etag(client, month="2026-09")
    again = await client.get(
        f"{API}/dashboard", params={"month": "2026-09"}, headers={"If-None-Match": first}
    )
    assert again.status_code == 304 and again.content == b""
    assert again.headers["etag"] == first
    assert await etag(client, month="2026-08") != first  # per month

    # A budget change, a category rename and a recategorisation each invalidate it.
    rent = await category_id(client, "Rent")
    seen = {first}
    await client.put(
        f"{API}/budgets/{rent}", json={"effective_from": "2026-09", "monthly_limit": "1.00"}
    )
    seen.add(tag := await etag(client, month="2026-09"))
    assert len(seen) == 2
    await client.patch(f"{API}/categories/{rent}", json={"name": "Home rent"})
    seen.add(await etag(client, month="2026-09"))
    assert len(seen) == 3
    page = (await client.get(f"{API}/transactions", params={"month": "2026-09", "limit": 1})).json()
    await client.patch(f"{API}/transactions/{page['items'][0]['id']}", json={"category_id": rent})
    seen.add(await etag(client, month="2026-09"))
    assert len(seen) == 4 and tag in seen


async def test_etags_differ_between_users(client: httpx.AsyncClient) -> None:
    assert (
        await etag(client)
        != (await client.get(f"{API}/dashboard", headers={"X-Test-User": "bob"})).headers["etag"]
    )
