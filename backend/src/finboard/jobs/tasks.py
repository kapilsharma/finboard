"""Celery task entry points. Keep them thin: parse ids, then call into services."""

import os
import uuid
from typing import Any

import structlog
from celery import Task
from celery.exceptions import SoftTimeLimitExceeded
from celery.worker.request import Request

from finboard.core.config import get_settings
from finboard.db.models import Job
from finboard.db.uow import UnitOfWork
from finboard.jobs import runtime
from finboard.jobs.celery_app import celery_app
from finboard.jobs.queue import CeleryJobQueue
from finboard.services.imports import ImportLimits, ImportService, mark_killed
from finboard.services.jobs import JobHandler, JobQueue, run_job

log = structlog.get_logger(__name__)


def job_queue() -> JobQueue:
    """The queue a worker uses to start follow-up jobs (tests replace it)."""
    return CeleryJobQueue(celery_app)


def _run(job_id: str, user_id: str, handler: JobHandler) -> None:
    runtime.run(
        lambda ctx: run_job(
            ctx.sessionmaker, user_id=uuid.UUID(user_id), job_id=uuid.UUID(job_id), handler=handler
        )
    )


async def _ping(_uow: UnitOfWork, _job: Job) -> dict[str, Any]:
    return {"pong": True, "worker_pid": os.getpid()}


@celery_app.task(name="maintenance.ping")  # type: ignore[untyped-decorator]
def ping(job_id: str, user_id: str) -> None:
    """Round-trip check: API → Redis → worker → Postgres. Used by tests and Settings > Data."""
    _run(job_id, user_id, _ping)


# ---------------------------------------------------------------- imports


class ParseRequest(Request):  # type: ignore[misc]
    """Runs in the parent worker process. When the hard time limit kills a hung parse, the
    task's own error handling never runs (and with no result backend Celery records nothing),
    so mark the job and import failed here."""

    def on_timeout(self, soft: bool, timeout: float) -> None:
        super().on_timeout(soft, timeout)
        if soft:
            return
        kwargs = self.kwargs or {}
        try:
            job_id, user_id = uuid.UUID(kwargs["job_id"]), uuid.UUID(kwargs["user_id"])
        except (KeyError, ValueError):
            return
        try:
            runtime.run(
                lambda ctx: mark_killed(
                    ctx.sessionmaker,
                    user_id=user_id,
                    job_id=job_id,
                    queue=job_queue(),
                    blobs=ctx.blobs,
                    registry=ctx.registry,
                    limits=ImportLimits.from_settings(ctx.settings),
                )
            )
        except Exception as exc:
            log.error("import.mark_killed_failed", job_id=str(job_id), error=type(exc).__name__)


class ParseTask(Task):  # type: ignore[misc]
    Request = ParseRequest


_settings = get_settings()


@celery_app.task(  # type: ignore[untyped-decorator]
    name="imports.process",
    base=ParseTask,
    soft_time_limit=_settings.parse_soft_time_limit,
    time_limit=_settings.parse_time_limit,
)
def process_import(job_id: str, user_id: str, secret_ref: str | None = None) -> None:
    """Parse one uploaded statement (ARCHITECTURE §7). Arguments are ids only; `secret_ref`
    points at a short-lived, single-use encrypted password in Redis (ADR-0027)."""

    async def work(ctx: runtime.WorkerContext) -> None:
        async def handler(uow: UnitOfWork, job: Job) -> dict[str, Any]:
            service = ImportService(
                uow,
                blobs=ctx.blobs,
                queue=job_queue(),
                registry=ctx.registry,
                limits=ImportLimits.from_settings(ctx.settings),
                secrets=ctx.secrets,
            )
            return await service.process(
                job, secret_ref=secret_ref, timeout_errors=(SoftTimeLimitExceeded,)
            )

        await run_job(
            ctx.sessionmaker, user_id=uuid.UUID(user_id), job_id=uuid.UUID(job_id), handler=handler
        )

    runtime.run(work)
