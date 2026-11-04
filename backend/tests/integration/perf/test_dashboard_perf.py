"""Performance budgets (ARCHITECTURE §14): `/dashboard` p95 < 200 ms for a user with 50k
transactions in a 100-user database; a `/transactions` page < 100 ms. Rows are generated
server-side (generate_series) so seeding takes seconds."""

import statistics
import time
import uuid
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.db.models import Account
from finboard.db.uow import unit_of_work
from finboard.domain.enums import CategoryType
from finboard.services.users import provision_user

API = "/api/v1"
USERS = 100
TARGET_TXNS = 50_000
OTHER_TXNS = 5_000
pytestmark = pytest.mark.perf

INSERT = text(
    """
    INSERT INTO txn (user_id, account_id, date, description_raw, description_norm, amount,
                     direction, category_id, type, categorised_by, needs_review, fingerprint,
                     fingerprint_version)
    SELECT CAST(:user_id AS uuid), (CAST(:accounts AS uuid[]))[1 + g % 3],
           DATE '2024-10-01' + (g % 730),
           'UPI DR MERCHANT ' || (g % 400), 'UPI DR MERCHANT ' || (g % 400),
           ((g * 7919) % 500000) / 100.0 + 1,
           CASE WHEN (CAST(:types AS text[]))[1 + g % :n_cats] = 'income' THEN 'credit'
                ELSE 'debit' END,
           (CAST(:categories AS uuid[]))[1 + g % :n_cats],
           (CAST(:types AS text[]))[1 + g % :n_cats],
           'manual', g % 97 = 0, md5(CAST(:user_id AS text) || g) || md5(g || CAST(:user_id AS text)), 1
    FROM generate_series(1, :n) AS g
    """
)


async def _seed_user(sm: async_sessionmaker[AsyncSession], name: str, n: int) -> uuid.UUID:
    async with unit_of_work(sm) as uow:
        user = await provision_user(uow, username=name, display_name=name)
        accounts = [
            await uow.accounts.add(Account(name=f"Account {i}", type="savings")) for i in range(3)
        ]
        categories = [c for c in await uow.categories.list() if c.type is not CategoryType.TRANSFER]
        await uow.session.execute(
            INSERT,
            {
                "user_id": str(user.id),
                "accounts": [a.id for a in accounts],
                "categories": [c.id for c in categories],
                "types": [c.type.value for c in categories],
                "n_cats": len(categories),
                "n": n,
            },
        )
        for c in categories[:10]:
            if c.type is CategoryType.EXPENSE:
                await uow.budgets.put(c.id, date(2024, 10, 1), Decimal("5000.00"))
        await uow.commit()
        return user.id


def p95(samples: list[float]) -> float:
    return statistics.quantiles(samples, n=20)[-1]


async def test_dashboard_and_transactions_within_budget(
    client: httpx.AsyncClient, sessionmaker: async_sessionmaker[AsyncSession], alice: Principal
) -> None:
    for i in range(USERS - 2):  # alice, bob and 98 others
        await _seed_user(sessionmaker, f"perf{i}", OTHER_TXNS)
    target = await _seed_user(sessionmaker, "perf_target", TARGET_TXNS)
    async with sessionmaker() as session:
        await session.execute(text("ANALYZE txn"))
        await session.commit()

    headers = {"X-Test-User": "perf_target"}
    # The test app authenticates users by name from a fixed map: add the target to it.
    backend = client._transport.app.state.auth_backend  # type: ignore[attr-defined]
    backend.users = {**backend.users, "perf_target": Principal(target, "perf_target", "Perf")}

    dashboard, page = [], []
    for i in range(45):
        started = time.perf_counter()
        response = await client.get(
            f"{API}/dashboard", params={"month": "2026-09"}, headers=headers
        )
        if i >= 5:  # warm-up
            dashboard.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200
        started = time.perf_counter()
        response = await client.get(
            f"{API}/transactions",
            params={"month": "2026-09", "limit": 50, "sort": "amount"},
            headers=headers,
        )
        if i >= 5:
            page.append((time.perf_counter() - started) * 1000)
        assert response.status_code == 200
    body = response.json()
    assert body["total"] > 1500
    print(f"\ndashboard p95 {p95(dashboard):.0f} ms; transactions page p95 {p95(page):.0f} ms")
    assert p95(dashboard) < 200
    assert p95(page) < 100
