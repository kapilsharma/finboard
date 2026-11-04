"""Dashboard and budgets API beyond the golden numbers."""

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.uow import unit_of_work
from finboard.domain.metrics import METRIC_DEFINITIONS
from finboard.services.demo import load_demo

from .categorisation_helpers import API, category_id


async def demo(sessionmaker: async_sessionmaker[AsyncSession], user: Principal) -> None:
    async with unit_of_work(sessionmaker, user.user_id) as uow:
        await load_demo(uow)


async def dashboard(client: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    response = await client.get(f"{API}/dashboard", params=params)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_empty_finboard(client: httpx.AsyncClient) -> None:
    assert (await client.get(f"{API}/dashboard")).json() is None
    assert (await client.get(f"{API}/dashboard/months")).json() == {"months": []}


async def test_months_default_month_and_trail(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    await demo(sessionmaker, alice)
    assert (await client.get(f"{API}/dashboard/months")).json() == {
        "months": ["2026-09", "2026-08", "2026-07"]
    }
    latest = await dashboard(client)
    assert latest["month"] == "2026-09"
    assert [m["month"] for m in (await dashboard(client, trail=2))["cashflow"]] == [
        "2026-08",
        "2026-09",
    ]

    july = await dashboard(client, month="2026-07")
    assert july["prev_month"] is None
    assert july["headline"]["income"]["delta_pct"] is None
    assert july["headline"]["net_saving"]["delta"] is None
    assert all(s["prev_amount"] is None for s in july["income_sources"])

    # A month without transactions after the data: zeros, no review count, July..Oct trail.
    october = await dashboard(client, month="2026-10")
    assert october["headline"]["income"]["value"] == "0.00"
    assert october["headline"]["savings_rate"]["value"] is None
    assert [m["month"] for m in october["cashflow"]][-1] == "2026-10"
    assert october["review_count"] == 0
    # Limits still show (nothing spent), so the user sees what's available.
    assert october["categories"]["summary"]["spent_in_limits"] == "0.00"

    assert (await client.get(f"{API}/dashboard", params={"month": "2026-13"})).status_code == 422
    assert (await client.get(f"{API}/dashboard", params={"trail": 0})).status_code == 422


async def test_budgets_take_effect_from_their_month(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    await demo(sessionmaker, alice)
    dining = await category_id(client, "Dining out")
    response = await client.put(
        f"{API}/budgets/{dining}", json={"effective_from": "2026-09", "monthly_limit": "5000.00"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["effective_from"] == "2026-09-01"

    def item(body: dict[str, Any]) -> dict[str, Any]:
        return next(i for i in body["categories"]["items"] if i["category"]["id"] == dining)

    assert item(await dashboard(client, month="2026-09"))["limit"] == "5000.00"
    assert item(await dashboard(client, month="2026-08"))["limit"] == "4000.00"  # unchanged before

    # null = no limit from this month on
    await client.put(
        f"{API}/budgets/{dining}", json={"effective_from": "2026-09", "monthly_limit": None}
    )
    september = await dashboard(client, month="2026-09")
    assert item(september)["status"] == "no_limit"
    assert september["categories"]["summary"]["over_count"] == 1

    listed = (await client.get(f"{API}/budgets", params={"month": "2026-09"})).json()
    by_category = {b["category_id"]: b["monthly_limit"] for b in listed["items"]}
    assert by_category[dining] is None and len(by_category) == 10

    salary = await category_id(client, "Salary")
    refused = await client.put(
        f"{API}/budgets/{salary}", json={"effective_from": "2026-09", "monthly_limit": "1.00"}
    )
    assert refused.status_code == 422
    negative = await client.put(
        f"{API}/budgets/{dining}", json={"effective_from": "2026-09", "monthly_limit": "-1"}
    )
    assert negative.status_code == 422


async def test_meta_serves_the_metric_definitions(client: httpx.AsyncClient) -> None:
    definitions = (await client.get(f"{API}/meta")).json()["metric_definitions"]
    assert definitions["spending"]["formula"] == METRIC_DEFINITIONS["spending"].formula
    assert {"income", "net_saving", "savings_rate", "account_net"} <= set(definitions)


async def test_demo_data_refuses_a_finboard_with_transactions(
    sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    import pytest

    from finboard.domain.errors import Conflict

    await demo(sessionmaker, alice)
    with pytest.raises(Conflict):
        await demo(sessionmaker, alice)


async def test_budget_history_and_undo(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    await demo(sessionmaker, alice)
    dining = await category_id(client, "Dining out")
    await client.put(
        f"{API}/budgets/{dining}", json={"effective_from": "2026-09", "monthly_limit": "5000.00"}
    )
    history = (await client.get(f"{API}/budgets/history", params={"category_id": dining})).json()[
        "items"
    ]
    assert [(h["effective_from"], h["monthly_limit"]) for h in history] == [
        ("2026-07-01", "4000.00"),
        ("2026-09-01", "5000.00"),
    ]
    assert (await client.delete(f"{API}/budgets/{dining}/2026-09")).status_code == 204
    september = await dashboard(client, month="2026-09")
    item = next(i for i in september["categories"]["items"] if i["category"]["id"] == dining)
    assert item["limit"] == "4000.00"
    assert (await client.delete(f"{API}/budgets/{dining}/2026-09")).status_code == 404
