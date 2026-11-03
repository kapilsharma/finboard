"""Background jobs, independent of Celery (ADR-0024).

`JobService.submit` records a job and hands it to a `JobQueue`. A worker later calls `run_job`,
which moves the job through queued → running → succeeded/failed, each step in its own
transaction so the API sees progress. Job state lives in Postgres, never in the broker.
"""

import uuid
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any, Protocol

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.db.models import Job
from finboard.db.uow import UnitOfWork, unit_of_work
from finboard.domain.enums import JobStatus
from finboard.domain.errors import FinboardError, NotFound, ServiceUnavailable

log = structlog.get_logger(__name__)

JobHandler = Callable[[UnitOfWork, Job], Awaitable[dict[str, Any] | None]]


class JobQueue(Protocol):
    async def enqueue(self, *, kind: str, job_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Hand the job to the workers. Arguments are ids only — never data or secrets."""
        ...


class JobService:
    def __init__(self, uow: UnitOfWork, queue: JobQueue) -> None:
        self.uow = uow
        self.queue = queue

    async def submit(self, kind: str, params: dict[str, Any] | None = None) -> Job:
        job = await self.uow.jobs.add(Job(kind=kind, status=JobStatus.QUEUED, params=params or {}))
        # Commit first: the worker must be able to read the job as soon as it is enqueued.
        await self.uow.commit()
        try:
            await self.queue.enqueue(kind=kind, job_id=job.id, user_id=job.user_id)
        except Exception as exc:
            log.error("job.enqueue_failed", job_id=str(job.id), kind=kind, error=type(exc).__name__)
            job.status = JobStatus.FAILED
            job.error = "The background worker queue is unavailable"
            job.finished_at = datetime.now(UTC)
            await self.uow.commit()
            raise ServiceUnavailable("The background worker queue is unavailable") from exc
        return job

    async def get(self, job_id: uuid.UUID) -> Job:
        job = await self.uow.jobs.get(job_id)
        if job is None:
            raise NotFound("Job not found")
        return job

    async def list_recent(self) -> Sequence[Job]:
        return await self.uow.jobs.list_recent()


async def run_job(
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    handler: JobHandler,
) -> None:
    """Execute a queued job. Safe to call twice for the same job (redelivery): runs only once."""
    structlog.contextvars.bind_contextvars(job_id=str(job_id), user_id=str(user_id))
    async with unit_of_work(sessionmaker, user_id) as uow:
        job = await uow.jobs.get(job_id, for_update=True)
        if job is None or job.status is not JobStatus.QUEUED:
            log.warning("job.skipped", status=job.status if job else None)
            return
        job.status = JobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await uow.commit()
    log.info("job.started", kind=job.kind)

    try:
        async with unit_of_work(sessionmaker, user_id) as uow:
            job = await _must_get(uow, job_id)
            result = await handler(uow, job)
            job.status = JobStatus.SUCCEEDED
            job.progress = 100
            job.result = result
            job.finished_at = datetime.now(UTC)
            await uow.commit()
        log.info("job.succeeded", kind=job.kind)
    except Exception as exc:
        async with unit_of_work(sessionmaker, user_id) as uow:
            job = await _must_get(uow, job_id)
            job.status = JobStatus.FAILED
            # Only domain errors carry user-safe messages; anything else may contain data.
            job.error = exc.detail if isinstance(exc, FinboardError) else "Internal error"
            job.finished_at = datetime.now(UTC)
            await uow.commit()
        log.exception("job.failed", kind=job.kind)
        raise


async def _must_get(uow: UnitOfWork, job_id: uuid.UUID) -> Job:
    job = await uow.jobs.get(job_id)
    if job is None:
        raise NotFound("Job not found")
    return job
