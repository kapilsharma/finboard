"""Housekeeping run by Celery beat (ARCHITECTURE §6).

    maintenance.expire_staged   hourly  discard staged imports past `expires_at` (7 days)
    maintenance.requeue_stale   5 min   re-enqueue jobs stuck `queued` (e.g. Redis was lost)
    maintenance.purge_jobs      daily   delete finished jobs older than 30 days, and exports

They work **one user at a time, under that user's row-level security**, exactly like a
request does, instead of as a database role that may read every user's rows (ADR-0037). The
only cross-user read is the list of user ids in `app_user`, which holds no financial data.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.db.uow import UnitOfWork, unit_of_work
from finboard.domain.enums import ImportStatus
from finboard.services.data import EXPORT_TASK, IMPORT_TASK
from finboard.services.jobs import JobQueue
from finboard.storage.blob import BlobStore, data_import_blob_key, export_blob_key

log = structlog.get_logger(__name__)

STALE_AFTER = timedelta(minutes=5)
KEEP_JOBS_FOR = timedelta(days=30)

PerUser = Callable[[UnitOfWork], Awaitable[int]]


def _now() -> datetime:
    return datetime.now(UTC)


class MaintenanceService:
    def __init__(
        self, sessionmaker: async_sessionmaker[AsyncSession], *, queue: JobQueue, blobs: BlobStore
    ) -> None:
        self.sessionmaker = sessionmaker
        self.queue = queue
        self.blobs = blobs

    async def _each_user(self, name: str, work: PerUser) -> int:
        async with unit_of_work(self.sessionmaker) as uow:
            users = await uow.users.all_ids()
        total = 0
        for user_id in users:
            try:
                async with unit_of_work(self.sessionmaker, user_id) as uow:
                    total += await work(uow)
            except Exception as exc:  # one user's problem doesn't stop the others
                log.error(
                    f"maintenance.{name}_failed", user_id=str(user_id), error=type(exc).__name__
                )
        log.info(f"maintenance.{name}", users=len(users), count=total)
        return total

    async def expire_staged(self, now: datetime | None = None) -> int:
        moment = now or _now()

        async def work(uow: UnitOfWork) -> int:
            batches = await uow.imports.expired(moment)
            keys = []
            for batch in batches:
                await uow.staged_rows.delete_all(batch.id)
                if batch.blob_key:
                    keys.append(batch.blob_key)
                batch.blob_key = None
                batch.status = ImportStatus.DISCARDED
                batch.error = "Expired: it waited more than 7 days without being committed"
            await uow.commit()
            for key in keys:
                await self.blobs.delete(key)
            return len(batches)

        return await self._each_user("expire_staged", work)

    async def requeue_stale(self, now: datetime | None = None) -> int:
        """A job still `queued` after 5 minutes was most likely lost with the broker. Enqueue
        it again; running it twice is harmless (`run_job` only runs a queued job once). A
        statement password never survives this: the import asks for it again."""
        cutoff = (now or _now()) - STALE_AFTER

        async def work(uow: UnitOfWork) -> int:
            jobs = await uow.jobs.stale_queued(cutoff)
            await uow.commit()
            for job in jobs:
                await self.queue.enqueue(kind=job.kind, job_id=job.id, user_id=job.user_id)
            return len(jobs)

        return await self._each_user("requeue_stale", work)

    async def purge_jobs(self, now: datetime | None = None) -> int:
        cutoff = (now or _now()) - KEEP_JOBS_FOR

        async def work(uow: UnitOfWork) -> int:
            jobs = await uow.jobs.finished_before(cutoff)
            ids: list[uuid.UUID] = [j.id for j in jobs]
            await uow.jobs.delete_ids(ids)
            await uow.commit()
            for job in jobs:
                if job.kind == EXPORT_TASK:
                    await self.blobs.delete(export_blob_key(job.user_id, job.id))
                elif job.kind == IMPORT_TASK:
                    await self.blobs.delete(data_import_blob_key(job.user_id, job.id))
            return len(ids)

        return await self._each_user("purge_jobs", work)
