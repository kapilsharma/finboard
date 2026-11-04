import uuid

import anyio.to_thread
from celery import Celery


class CeleryJobQueue:
    """`services.jobs.JobQueue` backed by Celery. The Celery task id is the job id."""

    def __init__(self, app: Celery) -> None:
        self.app = app

    async def enqueue(
        self,
        *,
        kind: str,
        job_id: uuid.UUID,
        user_id: uuid.UUID,
        secret_ref: str | None = None,
    ) -> None:
        kwargs = {"job_id": str(job_id), "user_id": str(user_id)}
        if secret_ref is not None:
            kwargs["secret_ref"] = secret_ref  # a reference, never the secret (ADR-0027)
        # send_task does blocking network I/O; keep it off the event loop.
        await anyio.to_thread.run_sync(
            lambda: self.app.send_task(kind, kwargs=kwargs, task_id=str(job_id))
        )
