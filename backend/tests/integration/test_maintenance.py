"""Housekeeping jobs (ARCHITECTURE §6), run per user under row-level security."""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.auth import Principal
from finboard.core.config import Settings
from finboard.db.models import ImportBatch, Job
from finboard.db.uow import unit_of_work
from finboard.jobs.celery_app import celery_app
from finboard.services.maintenance import MaintenanceService
from finboard.storage.blob import LocalFsBlobStore

from .conftest import RecordingJobQueue
from .imports_helpers import API, parsed, statement

BOB = {"X-Test-User": "bob"}


def service(
    sm: async_sessionmaker[AsyncSession], queue: RecordingJobQueue, settings: Settings
) -> MaintenanceService:
    return MaintenanceService(sm, queue=queue, blobs=LocalFsBlobStore(settings.blob_dir))


async def age(
    sm: async_sessionmaker[AsyncSession], user: Principal, model: type, column: str, days: int
) -> None:
    async with unit_of_work(sm, user.user_id) as uow:
        await uow.session.execute(
            update(model)
            .where(model.user_id == user.user_id)
            .values({column: datetime.now(UTC) - timedelta(days=days)})
        )
        await uow.commit()


async def test_expire_staged_discards_old_previews_only(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    alice: Principal,
) -> None:
    old = await parsed(client, job_queue, statement(seed=71, rows=3)[0])
    fresh = await parsed(client, job_queue, statement(seed=72, rows=3)[0], headers=BOB)
    await age(sessionmaker, alice, ImportBatch, "expires_at", 1)
    blob = next((settings.blob_dir / "users" / str(alice.user_id) / "imports").iterdir())

    assert await service(sessionmaker, job_queue, settings).expire_staged() == 1
    body = (await client.get(f"{API}/imports/{old['id']}")).json()
    assert body["status"] == "discarded" and body["rows"] is None and "Expired" in body["error"]
    assert not blob.exists()
    assert (await client.get(f"{API}/imports/{fresh['id']}", headers=BOB)).json()[
        "status"
    ] == "parsed"


async def test_requeue_stale_and_purge_old_jobs(
    client: httpx.AsyncClient,
    job_queue: RecordingJobQueue,
    sessionmaker: async_sessionmaker[AsyncSession],
    settings: Settings,
    alice: Principal,
) -> None:
    stuck = (await client.post(f"{API}/rules/apply", json={"dry_run": True})).json()["job"]
    job_queue.enqueued.clear()  # as if Redis lost it
    await age(sessionmaker, alice, Job, "created_at", 1)
    assert await service(sessionmaker, job_queue, settings).requeue_stale() == 1
    assert [e["job_id"] for e in job_queue.enqueued] == [uuid.UUID(stuck["id"])]

    await job_queue.drain_all()
    export = (await client.post(f"{API}/data/export")).json()["job"]
    await job_queue.drain_all()
    export_blob = settings.blob_dir / "users" / str(alice.user_id) / "exports" / export["id"]
    assert export_blob.exists()
    await age(sessionmaker, alice, Job, "finished_at", 31)
    assert await service(sessionmaker, job_queue, settings).purge_jobs() == 2
    assert (await client.get(f"{API}/jobs/{stuck['id']}")).status_code == 404
    assert not export_blob.exists()


def test_beat_schedules_the_housekeeping_tasks() -> None:
    schedule = {e["task"]: e["schedule"] for e in celery_app.conf.beat_schedule.values()}
    assert schedule == {
        "maintenance.expire_staged": 3600.0,
        "maintenance.requeue_stale": 300.0,
        "maintenance.purge_jobs": 86400.0,
    }
