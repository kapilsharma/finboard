"""Rules API: CRUD, validation, order, /rules/test, categorisation at import, category guards."""

from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.uow import unit_of_work
from finboard.domain.enums import CategorisedBy
from finboard.seed.rules import STARTER_RULES

from .categorisation_helpers import (
    API,
    account,
    add_txns,
    category_id,
    clear_rules,
    create_rule,
    txn,
)
from .conftest import RecordingJobQueue
from .imports_helpers import commit, create_account, parsed, statement


async def test_new_users_get_the_starter_pack(client: httpx.AsyncClient) -> None:
    rules = (await client.get(f"{API}/rules")).json()["items"]
    assert len(rules) == len(STARTER_RULES)
    assert [r["priority"] for r in rules] == list(range(len(STARTER_RULES)))
    assert all(r["enabled"] and r["hits"] == 0 for r in rules)


async def test_create_update_delete(client: httpx.AsyncClient) -> None:
    await clear_rules(client)
    food = await category_id(client, "Dining out")
    rule = await create_rule(client, pattern="swiggy", category_id=food, direction="debit")
    assert rule["priority"] == 0 and rule["pattern"] == "swiggy" and rule["direction"] == "debit"
    second = await create_rule(client, pattern="zomato", category_id=food)
    assert second["priority"] == 1  # appended

    response = await client.patch(
        f"{API}/rules/{rule['id']}", json={"amount_min": "10.00", "amount_max": "999.50"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["amount_min"] == "10.00" and response.json()["amount_max"] == "999.50"

    assert (await client.delete(f"{API}/rules/{rule['id']}")).status_code == 204
    assert (await client.get(f"{API}/rules/{rule['id']}")).status_code == 404


async def test_validation(client: httpx.AsyncClient) -> None:
    food = await category_id(client, "Dining out")

    async def post(**body: Any) -> httpx.Response:
        return await client.post(f"{API}/rules", json={"category_id": food, **body})

    bad_regex = await post(match_kind="regex", pattern="(unclosed")
    assert bad_regex.status_code == 422
    assert bad_regex.json()["code"] == "validation_failed"
    assert (await post(match_kind="contains", pattern="412345678901")).status_code == 422
    assert (await post(match_kind="contains", pattern="x" * 501)).status_code == 422
    assert (
        await post(match_kind="contains", pattern="A", amount_min="9.00", amount_max="1.00")
    ).status_code == 422
    float_amount = await post(match_kind="contains", pattern="A", amount_min=9.5)
    assert float_amount.status_code == 422  # money is never a float
    unknown = await client.post(
        f"{API}/rules",
        json={
            "match_kind": "contains",
            "pattern": "A",
            "category_id": "01900000-0000-7000-8000-000000000000",
        },
    )
    assert unknown.status_code == 422


async def test_reorder(client: httpx.AsyncClient) -> None:
    await clear_rules(client)
    food = await category_id(client, "Dining out")
    a, b, c = [await create_rule(client, pattern=p, category_id=food) for p in "ABC"]
    response = await client.post(f"{API}/rules/reorder", json={"ids": [c["id"], a["id"], b["id"]]})
    assert response.status_code == 200, response.text
    assert [r["pattern"] for r in response.json()["items"]] == ["C", "A", "B"]
    missing = await client.post(f"{API}/rules/reorder", json={"ids": [c["id"], a["id"]]})
    assert missing.status_code == 422
    twice = await client.post(f"{API}/rules/reorder", json={"ids": [a["id"], a["id"], b["id"]]})
    assert twice.status_code == 422


async def test_rule_test_counts_matches_changes_and_shadowing(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    await clear_rules(client)
    acc = await account(sessionmaker, alice)
    await add_txns(
        sessionmaker,
        alice,
        acc,
        [
            ("UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment", "250.00", "debit"),
            ("UPI/DR/412345678902/SWIGGY INSTAMART/YESB/x@ybl/Pay", "800.00", "debit"),
            ("POS XX1234 SWIGGY ONE", "99.00", "debit"),
            ("UPI/DR/412345678903/ZOMATO/YESB/z@ybl/Payment", "300.00", "debit"),
        ],
    )
    food, groceries = (
        await category_id(client, "Dining out"),
        await category_id(client, "Groceries"),
    )
    instamart = await create_rule(client, pattern="INSTAMART", category_id=groceries)

    body = {"match_kind": "contains", "pattern": "swiggy", "category_id": food}
    result = (await client.post(f"{API}/rules/test", json=body)).json()
    assert result["match_count"] == 3
    assert result["shadowed"] == 1  # INSTAMART runs first
    assert result["shadowed_by"] == [
        {"rule_id": instamart["id"], "pattern": "INSTAMART", "count": 1}
    ]
    assert result["would_change"] == 2 and result["uncategorised"] == 2
    assert len(result["sample"]) == 3

    # Tested as an edit of the INSTAMART rule at its own position: nothing runs before it.
    edit = {**body, "rule_id": instamart["id"]}
    result = (await client.post(f"{API}/rules/test", json=edit)).json()
    assert result["match_count"] == 3 and result["shadowed"] == 0

    narrowed = {**body, "amount_max": "100.00"}
    assert (await client.post(f"{API}/rules/test", json=narrowed)).json()["match_count"] == 1


async def test_rules_categorise_staged_rows_and_commit_counts_hits(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:
    data, expected = statement(seed=7, rows=30)
    await create_account(client, expected.account_hint)
    body = await parsed(client, job_queue, data)
    by_rule = [r for r in body["rows"] if r["categorised_by"] == "rule"]
    assert by_rule, "the starter pack should recognise some synthetic merchants"
    assert all(r["rule_id"] and r["category_id"] for r in by_rule)
    unmatched = [r for r in body["rows"] if r["category_id"] is None]
    assert body["counts"]["needs_review"] == len(unmatched)

    assert (await commit(client, body["id"])).status_code == 200
    rules = (await client.get(f"{API}/rules")).json()["items"]
    assert sum(r["hits"] for r in rules) == len(by_rule)
    assert all(r["last_hit_at"] for r in rules if r["hits"])
    # The commit queued transfer pairing.
    assert any(e["kind"] == "transfers.suggest" for e in job_queue.enqueued)


async def test_manual_choice_in_the_preview_survives_commit(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    data, expected = statement(seed=7, rows=10)
    await create_account(client, expected.account_hint)
    body = await parsed(client, job_queue, data)
    health = await category_id(client, "Health")
    response = await client.patch(
        f"{API}/imports/{body['id']}/rows/0", json={"category_id": health}
    )
    assert response.status_code == 200
    assert (await commit(client, body["id"])).status_code == 200
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        rows = await uow.txns.facts()
    manual = [r for r in rows if r.categorised_by is CategorisedBy.MANUAL]
    assert len(manual) == 1
    assert str(manual[0].category_id) == health and not manual[0].needs_review


async def test_category_type_change_cascades_to_transactions(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    acc = await account(sessionmaker, alice)
    created = await client.post(f"{API}/categories", json={"name": "Gifts", "type": "expense"})
    gifts = created.json()["id"]
    (txn_id,) = await add_txns(sessionmaker, alice, acc, [("GIFT SHOP", "500.00", "debit")])
    await client.patch(f"{API}/transactions/{txn_id}", json={"category_id": gifts})
    assert (await txn(client, txn_id))["type"] == "expense"

    response = await client.patch(f"{API}/categories/{gifts}", json={"type": "investment"})
    assert response.status_code == 200
    assert (await txn(client, txn_id))["type"] == "investment"


async def test_category_used_by_rules_cannot_be_deleted(client: httpx.AsyncClient) -> None:
    created = await client.post(f"{API}/categories", json={"name": "Pets", "type": "expense"})
    pets = created.json()["id"]
    rule = await create_rule(client, pattern="PETSHOP", category_id=pets)
    refused = await client.delete(f"{API}/categories/{pets}")
    assert refused.status_code == 409
    assert "Rules use this category" in refused.json()["detail"]
    await client.delete(f"{API}/rules/{rule['id']}")
    assert (await client.delete(f"{API}/categories/{pets}")).status_code == 204
