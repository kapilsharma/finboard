"""Celery task entry points. Keep them thin: parse ids, then call into services."""

import os
import uuid
from typing import Any

from finboard.db.models import Job
from finboard.db.uow import UnitOfWork
from finboard.jobs import runtime
from finboard.jobs.celery_app import celery_app
from finboard.services.jobs import JobHandler, run_job


def _run(job_id: str, user_id: str, handler: JobHandler) -> None:
    runtime.run(
        lambda sessionmaker: run_job(
            sessionmaker, user_id=uuid.UUID(user_id), job_id=uuid.UUID(job_id), handler=handler
        )
    )


async def _ping(_uow: UnitOfWork, _job: Job) -> dict[str, Any]:
    return {"pong": True, "worker_pid": os.getpid()}


@celery_app.task(name="maintenance.ping")  # type: ignore[untyped-decorator]
def ping(job_id: str, user_id: str) -> None:
    """Round-trip check: API → Redis → worker → Postgres. Used by tests and Settings > Data."""
    _run(job_id, user_id, _ping)
