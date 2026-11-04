"""Bridge from synchronous Celery tasks to the async services.

Each worker process gets one event loop, one async engine and one Redis client, created lazily on
first use (and recreated after a fork, detected by pid). Tasks run their coroutine on that loop,
so the API and the workers share exactly the same service code.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.core.config import Settings, get_settings
from finboard.db.engine import create_engine, create_sessionmaker
from finboard.parsers.registry import ParserRegistry, default_registry
from finboard.storage.blob import LocalFsBlobStore
from finboard.storage.secrets import RedisSecretStore


@dataclass(frozen=True)
class WorkerContext:
    settings: Settings
    sessionmaker: async_sessionmaker[AsyncSession]
    redis: Redis
    blobs: LocalFsBlobStore
    secrets: RedisSecretStore | None
    registry: ParserRegistry


_pid: int | None = None
_loop: asyncio.AbstractEventLoop | None = None
_context: WorkerContext | None = None


def _ensure_initialised() -> tuple[asyncio.AbstractEventLoop, WorkerContext]:
    global _pid, _loop, _context
    if _pid != os.getpid() or _loop is None or _context is None:
        settings = get_settings()
        _loop = asyncio.new_event_loop()
        # A worker runs one task at a time, so a small pool is enough.
        engine = create_engine(
            settings.model_copy(update={"db_pool_size": 2, "db_max_overflow": 2})
        )
        redis = Redis.from_url(settings.redis_url)
        secret = settings.secret_key.get_secret_value() if settings.secret_key else None
        _context = WorkerContext(
            settings=settings,
            sessionmaker=create_sessionmaker(engine),
            redis=redis,
            blobs=LocalFsBlobStore(settings.blob_dir),
            secrets=RedisSecretStore(redis, secret) if secret else None,
            registry=default_registry(tuple(settings.extra_parsers)),
        )
        _pid = os.getpid()
    return _loop, _context


def run[T](work: Callable[[WorkerContext], Awaitable[T]]) -> T:
    loop, context = _ensure_initialised()
    return loop.run_until_complete(work(context))
