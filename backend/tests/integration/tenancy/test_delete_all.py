"""Delete-all removes only the caller's rows and files (ROADMAP M5)."""

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.db.models import USER_OWNED_TABLES

from ..conftest import RecordingJobQueue
from ..imports_helpers import API, parsed, statement

BOB = {"X-Test-User": "bob"}


async def counts(engine: AsyncEngine, user: Principal) -> dict[str, int]:
    async with engine.begin() as conn:
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.user_id)}
        )
        return {
            t: (await conn.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
            for t in USER_OWNED_TABLES
        }


async def test_delete_all_is_tenant_scoped(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    app_engine: AsyncEngine,
    settings: Settings,
    alice: Principal,
    bob: Principal,
) -> None:
    for headers, seed in (({}, 61), (BOB, 62)):
        body = await parsed(client, job_queue, statement(seed=seed, rows=5)[0], headers=headers)
        response = await client.post(
            f"{API}/imports/{body['id']}/commit",
            json={"create_account": {"name": "Main", "type": "savings"}},
            headers=headers,
        )
        assert response.status_code == 200
        await client.patch(f"{API}/settings", json={"theme": "dark"}, headers=headers)
    await job_queue.drain_all()
    bob_before = await counts(app_engine, bob)
    bob_files = [
        p for p in (settings.blob_dir / "users" / str(bob.user_id)).rglob("*") if p.is_file()
    ]
    assert bob_files and bob_before["txn"] == 5

    response = await client.post(f"{API}/data/delete-all", json={"confirm": "DELETE ALL"})
    assert response.status_code == 202
    await job_queue.drain_all()
    job = (await client.get(f"{API}/jobs/{response.json()['job']['id']}")).json()
    assert job["status"] == "succeeded", job

    alice_after = await counts(app_engine, alice)
    assert {t: n for t, n in alice_after.items() if n} == {
        "category": alice_after["category"],  # the defaults again
        "rule": alice_after["rule"],
        "job": 1,  # the delete job itself
    }
    assert not (settings.blob_dir / "users" / str(alice.user_id)).exists()
    assert await counts(app_engine, bob) == bob_before
    assert all(p.exists() for p in bob_files)
    assert (await client.get(f"{API}/settings", headers=BOB)).json()["theme"] == "dark"
