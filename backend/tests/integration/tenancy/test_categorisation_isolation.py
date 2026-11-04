"""User B can't see or change user A's rules, transactions, review queue or transfers (ADR-0025),
and nothing B does can point at A's data."""

from typing import Any

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.domain.enums import AccountType

from ..categorisation_helpers import API, account, add_txns, category_id, create_rule
from ..conftest import RecordingJobQueue

BOB = {"X-Test-User": "bob"}


@pytest.fixture
async def alices(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> dict[str, Any]:
    savings = await account(sessionmaker, alice, "Savings")
    card = await account(sessionmaker, alice, "Card", AccountType.CREDIT_CARD)
    (debit,) = await add_txns(sessionmaker, alice, savings, [("CC BILL", "900.00", "debit")])
    await add_txns(sessionmaker, alice, card, [("PAYMENT RECEIVED", "900.00", "credit")])
    (pending,) = await add_txns(sessionmaker, alice, savings, [("ODD SHOP", "10.00", "debit")])
    await client.post(f"{API}/transfers/suggest")
    await job_queue.drain(("transfers.suggest",))
    (pair,) = (await client.get(f"{API}/transfers")).json()["items"]
    food = await category_id(client, "Dining out")
    rule = await create_rule(client, pattern="ALICE ONLY", category_id=food)
    return {
        "rule": rule["id"],
        "txn": str(debit),
        "pending": str(pending),
        "pair": pair["id"],
        "food": food,
        "account": str(savings),
    }


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/rules/{rule}", None),
        ("PATCH", "/rules/{rule}", {"enabled": False}),
        ("DELETE", "/rules/{rule}", None),
        ("GET", "/transactions/{txn}", None),
        ("PATCH", "/transactions/{txn}", {"notes": "bob was here"}),
        ("POST", "/transfers/{pair}/confirm", None),
        ("POST", "/transfers/{pair}/reject", None),
        ("DELETE", "/transfers/{pair}", None),
        ("POST", "/review/suggest-rule", {"transaction_id": "{pending}"}),
    ],
)
async def test_other_users_ids_are_404(
    client: httpx.AsyncClient,
    alices: dict[str, Any],
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    if body is not None:
        body = {k: v.format(**alices) if isinstance(v, str) else v for k, v in body.items()}
    response = await client.request(method, API + path.format(**alices), json=body, headers=BOB)
    assert response.status_code == 404, response.text
    assert (await client.get(f"{API}/rules/{alices['rule']}")).json()["enabled"] is True
    assert (await client.get(f"{API}/transfers")).json()["items"][0]["status"] == "suggested"


async def test_lists_are_per_user(client: httpx.AsyncClient, alices: dict[str, Any]) -> None:
    bobs_rules = (await client.get(f"{API}/rules", headers=BOB)).json()["items"]
    assert alices["rule"] not in {r["id"] for r in bobs_rules}
    assert (await client.get(f"{API}/transfers", headers=BOB)).json()["items"] == []
    assert (await client.get(f"{API}/review/groups", headers=BOB)).json()["total"] == 0
    exported = (await client.get(f"{API}/rules/export", headers=BOB)).text
    assert "ALICE ONLY" not in exported


async def test_bob_cannot_reference_alices_categories_accounts_or_transactions(
    client: httpx.AsyncClient, alices: dict[str, Any]
) -> None:
    rule = {"match_kind": "contains", "pattern": "X", "category_id": alices["food"]}
    assert (await client.post(f"{API}/rules", json=rule, headers=BOB)).status_code == 422
    bobs_food = await category_id(client, "Dining out", headers=BOB)
    with_account = {**rule, "category_id": bobs_food, "account_id": alices["account"]}
    assert (await client.post(f"{API}/rules", json=with_account, headers=BOB)).status_code == 422
    bulk = {"ids": [alices["txn"]], "category_id": bobs_food}
    assert (
        await client.post(f"{API}/transactions/bulk", json=bulk, headers=BOB)
    ).status_code == 404
    reorder = {"ids": [alices["rule"]]}
    assert (await client.post(f"{API}/rules/reorder", json=reorder, headers=BOB)).status_code == 422


async def test_bobs_apply_and_pairing_never_touch_alices_rows(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, alices: dict[str, Any]
) -> None:
    before = (await client.get(f"{API}/transactions/{alices['pending']}")).json()
    await client.post(f"{API}/rules/apply", json={"scope": "all", "dry_run": False}, headers=BOB)
    await client.post(f"{API}/transfers/suggest", headers=BOB)
    await job_queue.drain(("rules.apply", "transfers.suggest"))
    assert job_queue.failures == []
    assert (await client.get(f"{API}/transactions/{alices['pending']}")).json() == before
    assert (await client.get(f"{API}/transfers", headers=BOB)).json()["items"] == []


async def test_rls_hides_rules_and_pairs(
    app_engine: AsyncEngine, alices: dict[str, Any], alice: Principal, bob: Principal
) -> None:
    for user, visible in ((alice, True), (bob, False)):
        async with app_engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.user_id)}
            )
            for table, row_id in (("rule", alices["rule"]), ("transfer_pair", alices["pair"])):
                found = (
                    await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE id = :id"), {"id": row_id}
                    )
                ).scalar_one()
                assert found == (1 if visible else 0), (user.username, table)
