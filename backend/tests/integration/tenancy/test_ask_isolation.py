"""M4a tenancy: the spec path and the SQLite sandbox only ever see the caller's rows."""

from __future__ import annotations

import json

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal

from ..ask_helpers import API, ScriptedLlm, ask_app, ask_client, llm, spec_reply, sql_reply
from ..categorisation_helpers import account, add_txns

__all__ = ["ask_app", "ask_client", "llm"]  # shared fixtures

BOB = {"X-Test-User": "bob"}


async def test_sandbox_and_spec_see_only_the_callers_rows(
    ask_client: httpx.AsyncClient,
    llm: ScriptedLlm,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
    bob: Principal,
) -> None:
    a = await account(sessionmaker, alice)
    await add_txns(sessionmaker, alice, a, [("ALICE SHOP", "100.00", "debit")] * 2)
    b = await account(sessionmaker, bob)
    await add_txns(sessionmaker, bob, b, [("BOBONLY STORE", "999.00", "debit")] * 5)

    llm.replies += [
        json.dumps({"kind": "sql"}),
        sql_reply("SELECT merchant, COUNT(*) AS n FROM ai_txn GROUP BY merchant"),
        spec_reply(metric="spending", group_by=["merchant"]),
    ]
    sql = (await ask_client.post(f"{API}/ask", json={"question": "Merchants?"})).json()
    assert sql["result"]["rows"] == [["ALICE SHOP", 2]]
    spec = (await ask_client.post(f"{API}/ask", json={"question": "By merchant?"})).json()
    assert spec["result"]["rows"] == [["ALICE SHOP", "200.00"]]

    # Bob can't pin, see or delete Alice's questions.
    qid = sql["query"]["id"]
    assert (await ask_client.post(f"{API}/ask/{qid}/pin", json={}, headers=BOB)).status_code == 404
    assert (await ask_client.get(f"{API}/ask/history", headers=BOB)).json()["items"] == []
    await ask_client.post(f"{API}/ask/{qid}/pin", json={})
    (widget,) = (await ask_client.get(f"{API}/dashboard/widgets")).json()["items"]
    gone = await ask_client.delete(f"{API}/dashboard/widgets/{widget['id']}", headers=BOB)
    assert gone.status_code == 404
    assert (await ask_client.get(f"{API}/dashboard/widgets", headers=BOB)).json()["items"] == []
