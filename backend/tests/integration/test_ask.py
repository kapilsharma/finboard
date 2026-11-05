"""M4a: Ask Finboard through the real API, SQL and sandbox, with recorded model replies."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.ai import catalog
from finboard.ai.llm import LangChainClient
from finboard.auth import Principal
from finboard.db.uow import unit_of_work
from finboard.domain.enums import AccountType
from finboard.domain.errors import AiUnavailable
from finboard.services.demo import load_demo

from .ask_helpers import API, ScriptedLlm, ask_app, ask_client, llm, spec_reply, sql_reply
from .categorisation_helpers import account, add_txns

__all__ = ["ask_app", "ask_client", "llm"]  # shared fixtures

EATING_OUT = "Give me a monthly breakdown of eating out and provisions"
TOP3_SQL = (
    "SELECT category, SUM(signed_paise) AS spent_paise FROM ai_txn WHERE type = 'expense' "
    "GROUP BY category ORDER BY spent_paise DESC LIMIT 3"
)


async def _demo(sm: async_sessionmaker[AsyncSession], user: Principal) -> None:
    async with unit_of_work(sm, user.user_id) as uow:
        await load_demo(uow)
        await uow.commit()


async def _ask(client: httpx.AsyncClient, question: str, **kw: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/ask", json={"question": question}, **kw)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def test_off_by_default(client: httpx.AsyncClient) -> None:
    for method, path in (
        ("POST", "/ask"),
        ("GET", "/ask/history"),
        ("GET", "/dashboard/widgets"),
    ):
        response = await client.request(method, f"{API}{path}", json={"question": "hello?"})
        assert response.status_code == 404, path
        assert response.json()["code"] == "ai_off"
    assert (await client.get(f"{API}/ai/status")).json()["ask_available"] is False


async def test_needs_opt_in(ask_app: Any) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=ask_app),
        base_url="http://127.0.0.1",
        headers={"X-Finboard-Client": "1"},
    ) as c:
        assert (await c.get(f"{API}/ai/status")).json()["ask_available"] is True
        off = await c.post(f"{API}/ask", json={"question": "hello?"})
        assert off.status_code == 404 and off.json()["code"] == "ai_off"


async def test_golden_eating_out_and_provisions(
    ask_client: httpx.AsyncClient,
    llm: ScriptedLlm,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    """The issue's question → grouped bars whose totals equal the dashboard's."""
    await _demo(sessionmaker, alice)
    llm.replies.append(
        spec_reply(
            metric="spending",
            categories=["Dining out", "Groceries"],
            group_by=["month", "category"],
            start="2026-04-01",
            end="2026-09-30",
            chart="grouped_bar",
        )
    )
    body = await _ask(ask_client, EATING_OUT)
    q = body["query"]
    assert q["status"] == "ok" and q["path"] == "spec" and q["retries"] == 0
    assert q["chart"] == {
        "kind": "grouped_bar",
        "x": "month",
        "series": "category",
        "y": "spending",
    }
    cols = [c["name"] for c in body["result"]["columns"]]
    assert cols == ["month", "category", "spending"]
    got = {(r[0], r[1]): r[2] for r in body["result"]["rows"]}
    assert {m for m, _ in got} == {"2026-07", "2026-08", "2026-09"}

    for month in ("2026-07", "2026-08", "2026-09"):
        dash = (await ask_client.get(f"{API}/dashboard", params={"month": month})).json()
        spent = {i["category"]["name"]: i["spent"] for i in dash["categories"]["items"]}
        for name in ("Dining out", "Groceries"):
            assert got[(month, name)] == spent[name], (month, name)
    assert body["answer"].startswith("Spending on Dining out, Groceries by month and category")

    # The model saw the question, category paths and aliases; nothing else.
    (request,) = llm.requests
    assert request.task == "understand" and request.question == EATING_OUT
    assert "Dining out" in request.category_paths
    assert [a.alias for a in request.accounts] == ["Account A", "Account B"]


async def test_sql_path_retries_with_local_hint(
    ask_client: httpx.AsyncClient,
    llm: ScriptedLlm,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    await _demo(sessionmaker, alice)
    llm.replies += [
        json.dumps({"kind": "sql", "reason": "top-N over all time"}),
        sql_reply("SELECT * FROM txn"),  # rejected by the guard
        sql_reply(TOP3_SQL, "bar"),
    ]
    body = await _ask(ask_client, "My three biggest spending categories ever?")
    q = body["query"]
    assert q["status"] == "ok" and q["path"] == "sql" and q["retries"] == 1
    assert q["sql"].startswith("SELECT category, SUM(signed_paise) AS spent_paise")
    assert body["result"]["columns"] == [
        {"name": "category", "kind": "text"},
        {"name": "spent", "kind": "money"},
    ]
    assert body["result"]["rows"][0] == ["Rent", "96000.00"]  # 3 x 32,000, exact (paise)
    assert q["chart"]["kind"] == "bar"
    assert llm.requests[2].retry_hint == "table txn is not available; use ai_txn or ai_budget"
    assert q["tokens_in"] == 300


async def test_clarifying_question(ask_client: httpx.AsyncClient, llm: ScriptedLlm) -> None:
    llm.replies.append(json.dumps({"kind": "clarify", "question": "Which months?"}))
    body = await _ask(ask_client, "How am I doing?")
    assert body["query"]["status"] == "clarify"
    assert body["query"]["clarification"] == "Which months?"
    assert body["result"] is None


async def test_gives_up_after_two_retries(ask_client: httpx.AsyncClient, llm: ScriptedLlm) -> None:
    llm.replies += ["no json", "still none", "nope"]
    body = await _ask(ask_client, "Something odd?")
    assert body["query"]["status"] == "failed" and body["query"]["retries"] == 2
    assert len(llm.requests) == 3


async def test_pin_reruns_locally_and_history(
    ask_client: httpx.AsyncClient,
    llm: ScriptedLlm,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    await _demo(sessionmaker, alice)
    llm.replies += [
        spec_reply(metric="income", group_by=["month"], start="2026-07-01", end="2026-09-30"),
        json.dumps({"kind": "sql"}),
        sql_reply(TOP3_SQL),
    ]
    first = await _ask(ask_client, "Income by month?")
    second = await _ask(ask_client, "Top three categories?")
    for body in (first, second):
        pinned = await ask_client.post(f"{API}/ask/{body['query']['id']}/pin", json={})
        assert pinned.status_code == 201, pinned.text
    again = await ask_client.post(f"{API}/ask/{first['query']['id']}/pin", json={})
    assert again.status_code == 409

    asked = len(llm.requests)
    widgets = (await ask_client.get(f"{API}/dashboard/widgets")).json()["items"]
    assert len(llm.requests) == asked  # no model call on refresh
    assert [w["status"] for w in widgets] == ["ok", "ok"]
    assert widgets[0]["result"] == first["result"]
    assert widgets[1]["result"] == second["result"]
    assert widgets[0]["chart"]["kind"] in {"bar", "line"}

    # History keeps pinned questions when cleared.
    llm.replies.append(json.dumps({"kind": "clarify", "question": "Which?"}))
    await _ask(ask_client, "Hmm?")
    history = (await ask_client.get(f"{API}/ask/history")).json()["items"]
    assert [h["pinned"] for h in history] == [False, True, True]
    assert (await ask_client.delete(f"{API}/ask/history")).status_code == 204
    assert len((await ask_client.get(f"{API}/ask/history")).json()["items"]) == 2

    gone = await ask_client.delete(f"{API}/dashboard/widgets/{widgets[0]['id']}")
    assert gone.status_code == 204
    assert len((await ask_client.get(f"{API}/dashboard/widgets")).json()["items"]) == 1


async def test_pinned_sql_needs_updating_after_catalog_change(
    ask_client: httpx.AsyncClient,
    llm: ScriptedLlm,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _demo(sessionmaker, alice)
    llm.replies += [json.dumps({"kind": "sql"}), sql_reply(TOP3_SQL)]
    body = await _ask(ask_client, "Top three categories?")
    await ask_client.post(f"{API}/ask/{body['query']['id']}/pin", json={"title": "Top 3"})
    current = catalog.load()
    monkeypatch.setattr(
        catalog, "load", lambda: type(current)(current.version + 1, current.tables, current.text)
    )
    (widget,) = (await ask_client.get(f"{API}/dashboard/widgets")).json()["items"]
    assert widget["status"] == "needs_update" and widget["result"] is None
    assert widget["title"] == "Top 3"


async def test_rate_limit_is_a_friendly_503(
    ask_client: httpx.AsyncClient, llm: ScriptedLlm, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def busy(_: object) -> None:
        raise AiUnavailable("The AI provider is busy (rate limit); try again shortly")

    monkeypatch.setattr(llm, "complete", busy)
    response = await ask_client.post(f"{API}/ask", json={"question": "Spending by month?"})
    assert response.status_code == 503
    assert response.json()["code"] == "ai_unavailable"
    (failed,) = (await ask_client.get(f"{API}/ask/history")).json()["items"]
    assert failed["status"] == "failed"


# ---------------------------------------------------------------- privacy canaries

CANARY_ACCOUNT = "Salary Acme Canary 4321"
CANARY_MERCHANT = "CANARYMERCHANT ZQX"
CANARY_AMOUNT = "7777.77"


class RecordingChat(GenericFakeChatModel):
    """The real LangChain path, with a fake provider that keeps what it was sent."""

    seen: list[list[BaseMessage]] = Field(default_factory=list)

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.seen.append(messages)
        return super()._generate(messages, *args, **kwargs)


async def test_privacy_canaries_never_leave(
    ask_client: httpx.AsyncClient,
    ask_app: Any,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    await _demo(sessionmaker, alice)
    acc = await account(sessionmaker, alice, CANARY_ACCOUNT, AccountType.SAVINGS)
    await add_txns(sessionmaker, alice, acc, [(CANARY_MERCHANT, CANARY_AMOUNT, "debit")])
    chat = RecordingChat(
        messages=iter(
            AIMessage(content=c)
            for c in [
                "not json at all",  # retry 1
                json.dumps({"kind": "sql"}),
                sql_reply("SELECT nosuch FROM ai_txn"),  # sandbox error: retry 2
                sql_reply(
                    "SELECT merchant, signed_paise AS amount_paise, account FROM ai_txn "
                    "ORDER BY signed_paise DESC"
                ),
            ]
        )
    )
    ask_app.state.llm_factory = lambda: LangChainClient(chat, model="fake", timeout=5)
    body = await _ask(ask_client, "List every transaction with its merchant")
    assert body["query"]["status"] == "ok" and body["query"]["retries"] == 2
    rows = body["result"]["rows"]
    assert [CANARY_MERCHANT, CANARY_AMOUNT] in [r[:2] for r in rows]  # it was reachable locally

    sent = "\n".join(str(m.content) for messages in chat.seen for m in messages)
    assert len(chat.seen) == 4
    canaries = {CANARY_ACCOUNT, CANARY_MERCHANT, CANARY_AMOUNT, "Savings account", "Credit card"}
    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        for txn in (await uow.ask.sandbox_rows())[0]:
            canaries.add(str(txn[9]))  # every merchant / description
            if abs(txn[8]) >= 100:
                canaries.add(f"{abs(txn[8]):.2f}")  # every amount with paise
    leaked = sorted(c for c in canaries if c in sent)
    assert leaked == []
    assert "Account C — savings" in sent  # the alias went instead


def test_decimal_formatting_matches_the_api() -> None:
    assert f"{Decimal('7777.7700'):.2f}" == CANARY_AMOUNT


async def test_spec_queries_are_read_only_and_cut_off(
    sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    """Builder SQL runs on its own READ ONLY connection with a statement timeout."""
    from sqlalchemy.exc import DBAPIError

    from finboard.domain.errors import QueryTimeout

    async with unit_of_work(sessionmaker, alice.user_id) as uow:
        with pytest.raises(QueryTimeout):
            await uow.ask.run_read_only("SELECT pg_sleep(2)", {}, timeout_ms=200)
        with pytest.raises(DBAPIError, match="read-only"):
            await uow.ask.run_read_only("DELETE FROM category", {}, timeout_ms=3000)
        assert (
            await uow.ask.run_read_only(
                "SELECT current_setting('app.user_id')", {}, timeout_ms=3000
            )
        ) == [(str(alice.user_id),)]
