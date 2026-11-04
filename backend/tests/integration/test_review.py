"""Review queue, rule suggestion and manual categorisation (ARCHITECTURE §9, §10)."""

from datetime import date

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal

from .categorisation_helpers import API, account, add_txns, category_id, clear_rules, txn

SWIGGY_1 = "UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment"
SWIGGY_2 = "UPI/DR/598765432109/SWIGGY LTD/YESB/swiggy@ybl/Payment"


async def test_suggest_rule_for_swiggy_and_its_match_count(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    await clear_rules(client)
    acc = await account(sessionmaker, alice)
    first, *_ = await add_txns(
        sessionmaker,
        alice,
        acc,
        [
            (SWIGGY_1, "250.00", "debit"),
            (SWIGGY_2, "410.00", "debit"),
            ("POS XX9876 SWIGGY INSTAMART", "99.00", "debit"),
            ("UPI/DR/412345678999/ZOMATO/YESB/z@ybl/Payment", "300.00", "debit"),
        ],
    )
    response = await client.post(f"{API}/review/suggest-rule", json={"transaction_id": str(first)})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["suggestion"] == {"match_kind": "contains", "pattern": "SWIGGY"}
    assert body["test"]["match_count"] == 3
    assert body["test"]["uncategorised"] == 3 and body["test"]["shadowed"] == 0


async def test_groups_by_suggested_token_largest_first(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    await clear_rules(client)
    acc = await account(sessionmaker, alice)
    await add_txns(
        sessionmaker,
        alice,
        acc,
        [
            (SWIGGY_1, "250.00", "debit"),
            (SWIGGY_2, "410.50", "debit"),
            ("UPI/DR/412345678999/ZOMATO/YESB/z@ybl/Payment", "300.00", "debit"),
            ("UPI/CR/412345678000/YESB/Payment", "75.00", "credit"),  # nothing to suggest
            ("BIGBASKET", "120.00", "debit", date(2026, 8, 30)),  # another month
        ],
    )
    body = (await client.get(f"{API}/review/groups", params={"month": "2026-09"})).json()
    assert body["total"] == 4
    keys = [g["key"] for g in body["groups"]]
    assert keys == ["SWIGGY", "ZOMATO", "Other"]
    swiggy = body["groups"][0]
    assert swiggy["count"] == 2 and swiggy["debits"] == "660.50" and swiggy["credits"] == "0.00"
    assert swiggy["suggestion"] == {"match_kind": "contains", "pattern": "SWIGGY"}
    assert body["groups"][-1]["suggestion"] is None
    assert (await client.get(f"{API}/review/groups")).json()["total"] == 5
    bad = await client.get(f"{API}/review/groups", params={"month": "2026-13"})
    assert bad.status_code == 422


async def test_bulk_and_single_manual_categorisation_leave_the_queue(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    acc = await account(sessionmaker, alice)
    ids = await add_txns(
        sessionmaker,
        alice,
        acc,
        [
            ("ODD SHOP ONE", "10.00", "debit"),
            ("ODD SHOP TWO", "20.00", "debit"),
            ("X", "1.00", "credit"),
        ],
    )
    food = await category_id(client, "Dining out")
    response = await client.post(
        f"{API}/transactions/bulk", json={"ids": [str(i) for i in ids[:2]], "category_id": food}
    )
    assert response.status_code == 200 and response.json() == {"updated": 2}
    for txn_id in ids[:2]:
        row = await txn(client, txn_id)
        assert row["category_id"] == food and row["categorised_by"] == "manual"
        assert row["needs_review"] is False and row["rule_id"] is None and row["type"] == "expense"

    refunds = await category_id(client, "Refunds")
    response = await client.patch(
        f"{API}/transactions/{ids[2]}", json={"category_id": refunds, "notes": "cashback"}
    )
    assert response.status_code == 200
    assert response.json()["notes"] == "cashback" and response.json()["type"] == "income"
    assert (await client.get(f"{API}/review/groups")).json()["total"] == 0

    null = await client.patch(f"{API}/transactions/{ids[2]}", json={"category_id": None})
    assert null.status_code == 422
    unknown = await client.post(
        f"{API}/transactions/bulk",
        json={"ids": ["01900000-0000-7000-8000-000000000000"], "category_id": food},
    )
    assert unknown.status_code == 404
