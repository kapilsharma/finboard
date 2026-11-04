"""Transfer pairing end to end (ARCHITECTURE §9, OQ-6)."""

from datetime import date, timedelta
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.domain.enums import AccountType

from .categorisation_helpers import API, DAY, account, add_txns, category_id, clear_rules, txn
from .conftest import RecordingJobQueue
from .imports_helpers import commit, create_account, parsed, statement


async def suggest(client: httpx.AsyncClient, queue: RecordingJobQueue) -> list[dict[str, Any]]:
    response = await client.post(f"{API}/transfers/suggest")
    assert response.status_code == 202
    await queue.drain(("transfers.suggest",))
    body = (await client.get(f"{API}/transfers", params={"status": "suggested"})).json()
    items: list[dict[str, Any]] = body["items"]
    return items


async def test_card_payment_pair_is_suggested_then_confirmed(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    await clear_rules(client)
    savings = await account(sessionmaker, alice, "Savings")
    card = await account(sessionmaker, alice, "Card", AccountType.CREDIT_CARD)
    (debit,) = await add_txns(
        sessionmaker, alice, savings, [("NEFT CC BILL PAYMENT", "12000.00", "debit")]
    )
    (credit,) = await add_txns(
        sessionmaker,
        alice,
        card,
        [("PAYMENT RECEIVED THANK YOU", "12000.00", "credit", DAY + timedelta(days=2))],
    )
    pairs = await suggest(client, job_queue)
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair["debit"]["transaction"]["id"] == str(debit)
    assert pair["credit"]["transaction"]["id"] == str(credit)
    assert pair["days_apart"] == 2 and pair["credit"]["account"]["type"] == "credit_card"

    # Suggesting again finds nothing new (both sides are taken).
    assert len(await suggest(client, job_queue)) == 1

    confirmed = await client.post(f"{API}/transfers/{pair['id']}/confirm")
    assert confirmed.status_code == 200 and confirmed.json()["status"] == "confirmed"
    card_payment = await category_id(client, "Card payment")
    for txn_id in (debit, credit):
        row = await txn(client, txn_id)
        assert row["category_id"] == card_payment and row["categorised_by"] == "transfer"
        assert row["type"] == "transfer" and row["needs_review"] is False


async def test_own_transfer_and_window(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    a = await account(sessionmaker, alice, "A")
    b = await account(sessionmaker, alice, "B")
    await add_txns(sessionmaker, alice, a, [("IMPS TO SELF", "5000.00", "debit")])
    await add_txns(
        sessionmaker, alice, b, [("IMPS FROM SELF", "5000.00", "credit", DAY + timedelta(days=4))]
    )
    assert await suggest(client, job_queue) == []  # 4 days apart: too far

    (near,) = await add_txns(
        sessionmaker, alice, b, [("IMPS FROM SELF", "5000.00", "credit", DAY + timedelta(days=3))]
    )
    (pair,) = await suggest(client, job_queue)
    assert pair["credit"]["transaction"]["id"] == str(near)
    await client.post(f"{API}/transfers/{pair['id']}/confirm")
    row = await txn(client, near)
    assert row["category_id"] == await category_id(client, "Own transfer")


async def test_rejected_pairs_are_not_suggested_again(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    a = await account(sessionmaker, alice, "A")
    b = await account(sessionmaker, alice, "B")
    await add_txns(sessionmaker, alice, a, [("RENT", "15000.00", "debit")])
    await add_txns(sessionmaker, alice, b, [("REFUND", "15000.00", "credit")])
    (pair,) = await suggest(client, job_queue)
    rejected = await client.post(f"{API}/transfers/{pair['id']}/reject")
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert await suggest(client, job_queue) == []


async def test_never_pairs_into_loan_accounts(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    savings = await account(sessionmaker, alice, "Savings")
    loan = await account(sessionmaker, alice, "Home loan", AccountType.LOAN)
    await add_txns(sessionmaker, alice, savings, [("HDFC EMI", "30000.00", "debit")])
    await add_txns(sessionmaker, alice, loan, [("EMI RECEIVED", "30000.00", "credit")])
    assert await suggest(client, job_queue) == []


async def test_unpair_restores_rules_and_recategorising_one_side_undoes_the_pair(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    a = await account(sessionmaker, alice, "A")
    b = await account(sessionmaker, alice, "B")
    (debit,) = await add_txns(sessionmaker, alice, a, [("NEFT SALARY ADVANCE", "900.00", "debit")])
    (credit,) = await add_txns(sessionmaker, alice, b, [("NEFT SALARY", "900.00", "credit")])
    (pair,) = await suggest(client, job_queue)
    await client.post(f"{API}/transfers/{pair['id']}/confirm")

    # Recategorising one side by hand undoes the pair; the rules take the other side back
    # (the starter pack's SALARY rule categorises the credit).
    shopping = await category_id(client, "Shopping")
    await client.patch(f"{API}/transactions/{debit}", json={"category_id": shopping})
    assert (await txn(client, debit))["categorised_by"] == "manual"
    other = await txn(client, credit)
    assert other["categorised_by"] == "rule"
    assert other["category_id"] == await category_id(client, "Salary")
    listed = (await client.get(f"{API}/transfers")).json()["items"]
    assert [p["status"] for p in listed] == ["rejected"]


async def test_unpair_endpoint(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    await clear_rules(client)
    a = await account(sessionmaker, alice, "A")
    b = await account(sessionmaker, alice, "B")
    (debit,) = await add_txns(sessionmaker, alice, a, [("TRF", "50.00", "debit")])
    await add_txns(sessionmaker, alice, b, [("TRF", "50.00", "credit", date(2026, 9, 11))])
    (pair,) = await suggest(client, job_queue)
    await client.post(f"{API}/transfers/{pair['id']}/confirm")
    assert (await client.delete(f"{API}/transfers/{pair['id']}")).status_code == 204
    row = await txn(client, debit)
    assert row["categorised_by"] == "default" and row["needs_review"] is True
    assert await suggest(client, job_queue) == []  # undone pairs aren't suggested again


async def test_commit_queues_pairing(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue
) -> None:

    data, expected = statement(seed=8, rows=6)
    await create_account(client, expected.account_hint)
    body = await parsed(client, job_queue, data)
    assert (await commit(client, body["id"])).status_code == 200
    assert await job_queue.drain(("transfers.suggest",)) == 1
    assert job_queue.failures == []
