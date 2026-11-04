"""Performance budget (ROADMAP M3, ARCHITECTURE §14): 50k transactions x 200 rules re-applied in
under 10 s in a worker. Runs the real `rules.apply` task body, as a worker would."""

import json
import random
import secrets
import time
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.categorisation.normalise import normalise
from finboard.db.uow import unit_of_work
from finboard.domain.enums import CategorisedBy, Direction

from ..categorisation_helpers import API, account, clear_rules
from ..conftest import RecordingJobQueue

TXNS = 50_000
RULES = 200
BUDGET_SECONDS = 10.0
MERCHANTS = [f"MERCHANT{chr(65 + i % 26)}{chr(65 + i // 26 % 26)}" for i in range(400)]

pytestmark = pytest.mark.perf


async def _seed(
    client: httpx.AsyncClient, sm: async_sessionmaker[AsyncSession], user: Principal
) -> None:
    rng = random.Random(42)  # noqa: S311 (fake data)
    acc = await account(sm, user)
    categories = (await client.get(f"{API}/categories")).json()["items"]
    targets = [c["id"] for c in categories if c["type"] == "expense" and not c["is_system"]]

    # 180 plain rules for half the merchants (so half the rows match, many after a long scan)
    # and 20 regex rules, the slower kind, near the front so every row pays for them.
    pack_rules = [
        {
            "match_kind": "regex",
            "pattern": rf"\b(NEVER{i}|NOMATCH{i})\b",
            "category": "Shopping",
            "category_type": "expense",
        }
        for i in range(20)
    ] + [
        {
            "match_kind": "contains",
            "pattern": MERCHANTS[i * 2],
            "category": next(c["name"] for c in categories if c["id"] == targets[i % len(targets)]),
            "category_type": "expense",
        }
        for i in range(RULES - 20)
    ]

    response = await client.post(
        f"{API}/rules/import",
        json={"content": json.dumps({"finboard_rule_pack": 1, "rules": pack_rules})},
    )
    assert response.json()["added"] == RULES

    async with unit_of_work(sm, user.user_id) as uow:
        fallback = await uow.categories.by_system_key("uncategorized")
        assert fallback is not None
        start = date(2024, 1, 1)
        batch = []
        for i in range(TXNS):
            merchant = rng.choice(MERCHANTS)
            text = f"UPI/DR/{rng.randrange(10**11, 10**12)}/{merchant} PVT LTD/YESB/x@ybl/Pay"
            batch.append(
                {
                    "account_id": acc,
                    "date": start + timedelta(days=i % 700),
                    "description_raw": text,
                    "description_norm": normalise(text),
                    "amount": Decimal(rng.randrange(100, 500_000)) / 100,
                    "direction": Direction.DEBIT,
                    "category_id": fallback.id,
                    "type": fallback.type,
                    "categorised_by": CategorisedBy.DEFAULT,
                    "needs_review": True,
                    "fingerprint": secrets.token_hex(32),
                    "fingerprint_version": 1,
                }
            )
            if len(batch) == 2000:
                await uow.txns.insert_new(batch)
                batch = []
        await uow.txns.insert_new(batch)
        await uow.commit()


async def test_reapply_50k_transactions_with_200_rules(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    alice: Principal,
) -> None:
    await clear_rules(client)
    await _seed(client, sessionmaker, alice)
    response = await client.post(f"{API}/rules/apply", json={"scope": "all", "dry_run": False})
    job_id = response.json()["job"]["id"]

    started = time.perf_counter()
    await job_queue.drain(("rules.apply",))
    elapsed = time.perf_counter() - started

    job = (await client.get(f"{API}/jobs/{job_id}")).json()
    assert job["status"] == "succeeded", job
    assert job["result"]["scanned"] == TXNS
    assert TXNS * 0.3 < job["result"]["changed"] < TXNS * 0.7  # about half the merchants match
    print(f"\nre-apply: {elapsed:.2f} s")
    assert elapsed < BUDGET_SECONDS, f"re-apply took {elapsed:.1f} s"
