"""Celery application (ADR-0024). Start a worker with `finboard worker`."""

from celery import Celery

from finboard.core.config import Settings, get_settings

PARSE_QUEUE = "parse"
DEFAULT_QUEUE = "default"


def create_celery(settings: Settings) -> Celery:
    app = Celery("finboard", broker=settings.redis_url, include=["finboard.jobs.tasks"])
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],  # never pickle
        task_ignore_result=True,  # job state lives in Postgres
        result_backend=None,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        task_default_queue=DEFAULT_QUEUE,
        task_routes={"imports.*": {"queue": PARSE_QUEUE}},
        # Untrusted PDFs: recycle worker processes so a leak or a pathological file can't
        # accumulate (ARCHITECTURE §6). Memory is in KiB.
        worker_max_tasks_per_child=50,
        worker_max_memory_per_child=512_000,
        broker_connection_retry_on_startup=True,
        worker_hijack_root_logger=False,
        timezone="UTC",
    )
    return app


celery_app = create_celery(get_settings())
