import asyncio

from alembic import context
from sqlalchemy import Connection, text
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.ext.asyncio import create_async_engine

from finboard.core.config import get_settings
from finboard.db import models  # noqa: F401  (registers tables on Base.metadata)
from finboard.db.base import Base
from finboard.db.vector import Vector

ischema_names["vector"] = Vector  # so autogenerate/check can reflect pgvector columns

target_metadata = Base.metadata

# Any constant works; it only has to be the same for every instance running migrations.
_MIGRATION_LOCK_ID = 727_274_001


def _database_url() -> str:
    return context.config.get_main_option("sqlalchemy.url") or get_settings().migration_database_url


def _do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        # Several API instances may start together; only one migrates at a time.
        connection.execute(text("SELECT pg_advisory_xact_lock(:id)"), {"id": _MIGRATION_LOCK_ID})
        context.run_migrations()


async def _run_async_migrations() -> None:
    engine = create_async_engine(_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=_database_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(_run_async_migrations())
