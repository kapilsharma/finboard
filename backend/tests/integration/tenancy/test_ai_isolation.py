"""M3a tenancy: suggestions only ever use the caller's own transactions and embeddings."""

from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.ai.text import embedding_key
from finboard.auth import Principal
from finboard.db.uow import unit_of_work

from ..ai_helpers import API, ai_app, ai_client, categorise, category_ids
from ..categorisation_helpers import account, add_txns
from ..conftest import RecordingJobQueue

__all__ = ["ai_app", "ai_client"]  # shared fixtures

BOB = {"X-Test-User": "bob"}


async def test_neighbours_never_cross_users(
    ai_client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
    bob: Principal,
    job_queue: RecordingJobQueue,
) -> None:
    # Bob has a categorised history of exactly the merchant Alice is about to import.
    bob_acc = await account(sessionmaker, bob)
    bob_rows = await add_txns(
        sessionmaker, bob, bob_acc, [(f"UPI/ZEPTO/ORDER {n}", "300.00", "debit") for n in range(6)]
    )
    await categorise(
        ai_client, bob_rows, (await category_ids(ai_client, "bob"))["Groceries"], "bob"
    )
    # Alice has only an unrelated categorised history.
    alice_acc = await account(sessionmaker, alice)
    alice_rows = await add_txns(
        sessionmaker, alice, alice_acc, [("NETFLIX SUBSCRIPTION", "649.00", "debit")]
    )
    await categorise(ai_client, alice_rows, (await category_ids(ai_client))["Entertainment"])
    (new,) = await add_txns(
        sessionmaker, alice, alice_acc, [("UPI/ZEPTO/ORDER 99", "310.00", "debit")]
    )

    for headers in ({}, BOB):
        assert (
            await ai_client.patch(f"{API}/ai/settings", json={"suggestions": True}, headers=headers)
        ).status_code == 200
    await job_queue.drain(("ai.embed_all",))
    assert not job_queue.failures

    # Each user's embeddings cover only their own rows.
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        assert (await uow.embeddings.counts(ai_client_model(ai_client)))[1] == 2
    mine = (await ai_client.get(f"{API}/transactions/{new}/suggestions")).json()
    examples = [e["id"] for item in mine["items"] for e in item["examples"]]
    assert not set(examples) & {str(i) for i in bob_rows}
    assert all(item["category"]["name"] != "Groceries" for item in mine["items"])

    # Bob can't ask about Alice's transaction.
    theirs = await ai_client.get(f"{API}/transactions/{new}/suggestions", headers=BOB)
    assert theirs.status_code == 404
    assert theirs.json()["code"] != "ai_off"


def ai_client_model(client: httpx.AsyncClient) -> str:
    app = client._transport.app  # type: ignore[attr-defined]
    return embedding_key(str(app.state.settings.embed_model))
