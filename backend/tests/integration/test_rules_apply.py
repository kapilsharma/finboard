"""`rules.apply`: provenance decides what re-apply may overwrite (ARCHITECTURE §9).

default → always · rule → scope=all · manual → only with include_manual · transfer → never.
"""

import uuid
from typing import Any

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.domain.enums import CategorisedBy

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

SWIGGY = "UPI/DR/412345678901/SWIGGY LTD/YESB/swiggy@ybl/Payment"


async def apply(client: httpx.AsyncClient, queue: RecordingJobQueue, **body: Any) -> dict[str, Any]:
    response = await client.post(f"{API}/rules/apply", json=body)
    assert response.status_code == 202, response.text
    job_id = response.json()["job"]["id"]
    await queue.drain(("rules.apply",))
    job = (await client.get(f"{API}/jobs/{job_id}")).json()
    assert job["status"] == "succeeded", job
    result: dict[str, Any] = job["result"]
    return result


@pytest.fixture
async def setup(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> dict[str, Any]:
    """One SWIGGY transaction per provenance, each in some other category, plus a SWIGGY rule."""
    await clear_rules(client)
    acc = await account(sessionmaker, alice)
    row = [(SWIGGY, "250.00", "debit")]
    ids = {
        "default": (await add_txns(sessionmaker, alice, acc, row))[0],
        "rule": (
            await add_txns(
                sessionmaker,
                alice,
                acc,
                row,
                categorised_by=CategorisedBy.RULE,
                category_key="own_transfer",
            )
        )[0],
        "manual": (
            await add_txns(
                sessionmaker,
                alice,
                acc,
                row,
                categorised_by=CategorisedBy.MANUAL,
                category_key="own_transfer",
            )
        )[0],
        "transfer": (
            await add_txns(
                sessionmaker,
                alice,
                acc,
                row,
                categorised_by=CategorisedBy.TRANSFER,
                category_key="own_transfer",
            )
        )[0],
    }
    food = await category_id(client, "Dining out")
    rule = await create_rule(client, pattern="SWIGGY", category_id=food)
    return {"ids": ids, "food": food, "rule": rule}


async def categories(client: httpx.AsyncClient, ids: dict[str, uuid.UUID]) -> dict[str, str]:
    return {k: (await txn(client, v))["category_id"] for k, v in ids.items()}


async def test_dry_run_changes_nothing_and_returns_the_diff(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, setup: dict[str, Any]
) -> None:
    before = await categories(client, setup["ids"])
    result = await apply(client, job_queue, scope="all", include_manual=True, dry_run=True)
    assert result["dry_run"] is True
    assert result["changed"] == 3  # default, rule and manual; never transfer
    assert sum(t["count"] for t in result["transitions"]) == 3
    assert {t["to_category_id"] for t in result["transitions"]} == {setup["food"]}
    assert len(result["sample"]) == 3
    assert await categories(client, setup["ids"]) == before


async def test_uncategorised_scope_only_touches_defaults(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, setup: dict[str, Any]
) -> None:
    result = await apply(client, job_queue, scope="uncategorised", dry_run=False)
    assert result["changed"] == 1
    after = await categories(client, setup["ids"])
    assert after["default"] == setup["food"]
    assert setup["food"] not in (after["rule"], after["manual"], after["transfer"])
    moved = await txn(client, setup["ids"]["default"])
    assert moved["categorised_by"] == "rule" and moved["rule_id"] == setup["rule"]["id"]
    assert moved["needs_review"] is False and moved["type"] == "expense"
    rule = (await client.get(f"{API}/rules/{setup['rule']['id']}")).json()
    assert rule["hits"] == 1


async def test_scope_all_overwrites_rule_rows_but_not_manual_or_transfer(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, setup: dict[str, Any]
) -> None:
    await apply(client, job_queue, scope="all", dry_run=False)
    after = await categories(client, setup["ids"])
    assert after["default"] == after["rule"] == setup["food"]
    assert setup["food"] not in (after["manual"], after["transfer"])


async def test_include_manual_overwrites_manual_never_transfer(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, setup: dict[str, Any]
) -> None:
    await apply(client, job_queue, scope="all", include_manual=True, dry_run=False)
    after = await categories(client, setup["ids"])
    assert after["manual"] == setup["food"]
    assert after["transfer"] != setup["food"]
    assert (await txn(client, setup["ids"]["transfer"]))["categorised_by"] == "transfer"


async def test_manual_rows_never_fall_back_to_uncategorised(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, setup: dict[str, Any]
) -> None:
    await client.delete(f"{API}/rules/{setup['rule']['id']}")
    before = await txn(client, setup["ids"]["manual"])
    await apply(client, job_queue, scope="all", include_manual=True, dry_run=False)
    after = await txn(client, setup["ids"]["manual"])
    assert after["category_id"] == before["category_id"] and after["categorised_by"] == "manual"


async def test_rule_rows_whose_rule_no_longer_matches_go_back_to_review(
    client: httpx.AsyncClient, job_queue: RecordingJobQueue, setup: dict[str, Any]
) -> None:
    await client.delete(f"{API}/rules/{setup['rule']['id']}")
    await apply(client, job_queue, scope="all", dry_run=False)
    row = await txn(client, setup["ids"]["rule"])
    assert row["categorised_by"] == "default" and row["needs_review"] is True
    assert row["category_id"] == await category_id(client, "Uncategorized")


async def test_regex_timeout_disables_and_flags_the_rule(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    await clear_rules(client)
    acc = await account(sessionmaker, alice)
    await add_txns(sessionmaker, alice, acc, [("A" * 60 + "B", "10.00", "debit")])
    food = await category_id(client, "Dining out")
    evil = await create_rule(client, match_kind="regex", pattern="(A|AA)+$", category_id=food)
    result = await apply(client, job_queue, dry_run=False)
    assert result["disabled_rule_ids"] == [evil["id"]]
    rule = (await client.get(f"{API}/rules/{evil['id']}")).json()
    assert rule["enabled"] is False and "too long" in rule["error"]
    # Re-enabling clears the flag.
    response = await client.patch(f"{API}/rules/{evil['id']}", json={"enabled": True})
    assert response.json()["error"] is None
