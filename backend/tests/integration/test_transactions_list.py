"""GET /transactions: filters, search, sort, keyset paging, totals (ARCHITECTURE §10)."""

from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.uow import unit_of_work
from finboard.services.demo import load_demo

from .categorisation_helpers import API, category_id


@pytest.fixture(autouse=True)
async def _demo(sessionmaker: async_sessionmaker[AsyncSession], alice: Principal) -> None:
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        await load_demo(uow)


async def listing(client: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/transactions", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_month_totals_match_the_dashboard(client: httpx.AsyncClient) -> None:
    body = await listing(client, month="2026-09", limit=200)
    assert body["total"] == 29 and len(body["items"]) == 29 and body["next_cursor"] is None
    assert body["sums"] == {
        "income": "142702.04",
        "spending": "96040.38",
        "invested": "15000.00",
        "transfers": "24966.75",
    }
    first = body["items"][0]
    assert first["date"] == "2026-09-28"  # newest first by default
    assert {"account_name", "category_name", "description"} <= set(first)


async def test_filters(client: httpx.AsyncClient) -> None:
    review = await listing(client, month="2026-09", needs_review="true")
    assert review["total"] == 2 and all(t["needs_review"] for t in review["items"])
    groceries = await category_id(client, "Groceries")
    by_category = await listing(client, month="2026-09", category_id=groceries)
    assert by_category["total"] == 6 and {t["category_name"] for t in by_category["items"]} == {
        "Groceries"
    }
    accounts = (await client.get(f"{API}/accounts")).json()["items"]
    savings = next(a["id"] for a in accounts if a["name"] == "Savings account")
    by_account = await listing(client, month="2026-09", account_id=savings)
    assert {t["account_name"] for t in by_account["items"]} == {"Savings account"}
    transfers = await listing(client, type="transfer")
    assert transfers["total"] == 3 and transfers["sums"]["spending"] == "0.00"
    ranged = await listing(client, **{"from": "2026-08-01", "to": "2026-08-31"})
    assert ranged["total"] == (await listing(client, month="2026-08"))["total"]
    both = await client.get(
        f"{API}/transactions", params={"month": "2026-08", "from": "2026-08-01"}
    )
    assert both.status_code == 422


async def test_search_matches_description_account_and_category(client: httpx.AsyncClient) -> None:
    assert (await listing(client, month="2026-09", q="swiggy"))["total"] == 5
    assert (await listing(client, month="2026-09", q="SWIGGY / ZOMATO"))["total"] == 5
    assert (await listing(client, month="2026-09", q="dining"))["total"] == 5  # category name
    assert (await listing(client, month="2026-09", q="credit card"))["total"] > 0  # account name
    assert (await listing(client, month="2026-09", q="100%_\\"))["total"] == 0  # LIKE escaped


@pytest.mark.parametrize("sort", ["date", "description", "account", "category", "type", "amount"])
@pytest.mark.parametrize("order", ["asc", "desc"])
async def test_keyset_pages_cover_everything_once_in_order(
    client: httpx.AsyncClient, sort: str, order: str
) -> None:
    everything = await listing(client, sort=sort, order=order, limit=200)
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"sort": sort, "order": order, "limit": 7}
        if cursor:
            params["cursor"] = cursor
        page = await listing(client, **params)
        seen += [t["id"] for t in page["items"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert seen == [t["id"] for t in everything["items"]]
    assert len(seen) == len(set(seen)) == everything["total"] == 84


async def test_amount_sort_and_bad_input(client: httpx.AsyncClient) -> None:
    amounts = [
        t["amount"] for t in (await listing(client, sort="amount", order="desc", limit=3))["items"]
    ]
    assert amounts[0] == "160000.00" or float(amounts[0]) >= float(amounts[1])
    assert (
        await client.get(f"{API}/transactions", params={"cursor": "nonsense"})
    ).status_code == 422
    assert (await client.get(f"{API}/transactions", params={"sort": "id"})).status_code == 422
    assert (await client.get(f"{API}/transactions", params={"limit": 201})).status_code == 422
