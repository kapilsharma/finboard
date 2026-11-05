"""M3a: category suggestions (ROADMAP M3a, ADR-0038). Off by default, per-user opt-in,
never applied automatically, accepting one is a manual categorisation."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.services.ai import AiConfig

from .ai_helpers import API, ai_app, ai_client, categorise, category_ids
from .categorisation_helpers import account, add_txns
from .conftest import RecordingJobQueue
from .imports_helpers import commit, create_account, parsed, statement

__all__ = ["ai_app", "ai_client"]  # shared fixtures

GROCERIES = [
    "UPI/BIGBASKET/ORDER 4411",
    "UPI/BIGBASKET/ORDER 9921",
    "UPI-BIGBASKET-GROCERY",
    "POS BIGBASKET BANGALORE",
]
DINING = ["UPI/SWIGGY/FOOD ORDER", "UPI/SWIGGY/DINNER", "UPI-SWIGGY-INSTAMART LUNCH"]


async def _history(
    client: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession], user: Principal
) -> tuple[list[object], list[object]]:
    """Categorised groceries and dining (by hand), then two new uncategorised rows."""
    acc = await account(sm, user)
    groceries = await add_txns(sm, user, acc, [(d, "812.00", "debit") for d in GROCERIES])
    dining = await add_txns(sm, user, acc, [(d, "420.00", "debit") for d in DINING])
    cats = await category_ids(client, user.username)
    await categorise(client, groceries, cats["Groceries"], user.username)
    await categorise(client, dining, cats["Dining out"], user.username)
    new = await add_txns(
        sm,
        user,
        acc,
        [
            ("UPI/BIGBASKET/ORDER 7310", "655.00", "debit"),
            ("UPI/SWIGGY/FOOD ORDER 2", "380.00", "debit"),
        ],
    )
    return list(new), groceries + dining


async def test_off_by_default(client: httpx.AsyncClient) -> None:
    status = (await client.get(f"{API}/ai/status")).json()
    assert status["suggestions_available"] is False
    assert status["suggestions_enabled"] is False
    assert status["ask_available"] is False
    refused = await client.patch(f"{API}/ai/settings", json={"suggestions": True})
    assert refused.status_code == 409


async def test_suggestions_404_until_opted_in(
    ai_client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    new, _ = await _history(ai_client, sessionmaker, alice)
    off = await ai_client.get(f"{API}/transactions/{new[0]}/suggestions")
    assert off.status_code == 404
    assert off.json()["code"] == "ai_off"


async def test_suggests_without_applying(
    ai_client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
    job_queue: RecordingJobQueue,
    ai_app: FastAPI,
) -> None:
    new, _ = await _history(ai_client, sessionmaker, alice)
    on = await ai_client.patch(f"{API}/ai/settings", json={"suggestions": True})
    assert on.status_code == 200 and on.json()["suggestions_enabled"] is True
    config = AiConfig.from_settings(ai_app.state.settings)
    if config.uses_embeddings:
        assert [e["kind"] for e in job_queue.enqueued] == ["ai.embed_all"]
        await job_queue.drain(("ai.embed_all",))
        assert not job_queue.failures
        status = (await ai_client.get(f"{API}/ai/status")).json()
        assert status["embedded"] == status["transactions"] == 9

    cats = await category_ids(ai_client)
    groceries = (await ai_client.get(f"{API}/transactions/{new[0]}/suggestions")).json()
    assert groceries["method"] == ("embedding" if config.uses_embeddings else "trigram")
    assert groceries["items"][0]["category"]["id"] == cats["Groceries"]
    assert groceries["items"][0]["confidence"] > 0.5
    examples = groceries["items"][0]["examples"]
    assert 1 <= len(examples) <= 3
    assert all("BIGBASKET" in e["description"] for e in examples)
    dining = (await ai_client.get(f"{API}/transactions/{new[1]}/suggestions")).json()
    assert dining["items"][0]["category"]["id"] == cats["Dining out"]

    # Nothing was applied: the row is still uncategorised and waiting for review.
    row = (await ai_client.get(f"{API}/transactions/{new[0]}")).json()
    assert row["needs_review"] is True
    assert row["categorised_by"] == "default"

    # Accepting is an ordinary manual categorisation.
    accepted = await ai_client.patch(
        f"{API}/transactions/{new[0]}", json={"category_id": cats["Groceries"]}
    )
    assert accepted.status_code == 200
    assert accepted.json()["categorised_by"] == "manual"


async def test_only_rule_or_manual_rows_vote(
    ai_client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    """Uncategorised look-alikes are not evidence; with no categorised history, no guess."""
    acc = await account(sessionmaker, alice)
    ids = await add_txns(
        sessionmaker, alice, acc, [(d, "812.00", "debit") for d in [*GROCERIES, *DINING]]
    )
    await ai_client.patch(f"{API}/ai/settings", json={"suggestions": True})
    result = (await ai_client.get(f"{API}/transactions/{ids[0]}/suggestions")).json()
    assert result["items"] == []


async def test_turning_off_hides_suggestions(
    ai_client: httpx.AsyncClient,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    new, _ = await _history(ai_client, sessionmaker, alice)
    await ai_client.patch(f"{API}/ai/settings", json={"suggestions": True})
    await ai_client.patch(f"{API}/ai/settings", json={"suggestions": False})
    off = await ai_client.get(f"{API}/transactions/{new[0]}/suggestions")
    assert off.status_code == 404


async def test_import_commit_embeds_only_for_opted_in_users(
    ai_client: httpx.AsyncClient, job_queue: RecordingJobQueue, ai_app: FastAPI
) -> None:
    if not AiConfig.from_settings(ai_app.state.settings).uses_embeddings:
        pytest.skip("trigram suggestions need no embeddings")
    for seed, opted_in in ((1, False), (4, True)):
        if opted_in:
            await ai_client.patch(f"{API}/ai/settings", json={"suggestions": True})
            await job_queue.drain(("ai.embed_all",))
        data, expected = statement(seed=seed, rows=6)
        await create_account(ai_client, expected.account_hint, name=f"Acc {seed}")
        preview = await parsed(ai_client, job_queue, data)
        before = [e["kind"] for e in job_queue.enqueued]
        assert (await commit(ai_client, preview["id"])).status_code == 200
        queued = [e["kind"] for e in job_queue.enqueued[len(before) :]]
        assert ("ai.embed" in queued) is opted_in
    await job_queue.drain(("ai.embed",))
    assert not job_queue.failures
    status = (await ai_client.get(f"{API}/ai/status")).json()
    assert status["embedded"] == status["transactions"] == 12
