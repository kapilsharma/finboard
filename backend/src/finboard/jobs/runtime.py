"""Bridge from synchronous Celery tasks to the async services.

Each worker process gets one event loop and one async engine, created lazily on first use (and
recreated after a fork, detected by pid). Tasks run their coroutine on that loop, so the API and
the workers share exactly the same service code.
"""

import asyncio
import os
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.core.config import get_settings
from finboard.db.engine import create_engine, create_sessionmaker

_pid: int | None = None
_loop: asyncio.AbstractEventLoop | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def _ensure_initialised() -> tuple[asyncio.AbstractEventLoop, async_sessionmaker[AsyncSession]]:
    global _pid, _loop, _sessionmaker
    if _pid != os.getpid() or _loop is None or _sessionmaker is None:
        settings = get_settings()
        _loop = asyncio.new_event_loop()
        # A worker runs one task at a time, so a small pool is enough.
        engine = create_engine(
            settings.model_copy(update={"db_pool_size": 2, "db_max_overflow": 2})
        )
        _sessionmaker = create_sessionmaker(engine)
        _pid = os.getpid()
    return _loop, _sessionmaker


def run[T](work: Callable[[async_sessionmaker[AsyncSession]], Awaitable[T]]) -> T:
    loop, sessionmaker = _ensure_initialised()
    return loop.run_until_complete(work(sessionmaker))
