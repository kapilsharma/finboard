import asyncio

from alembic import command
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.core.config import Settings
from finboard.db import migrate
from finboard.db.migrate import alembic_config


async def test_models_and_migrations_agree(settings: Settings, owner_engine: AsyncEngine) -> None:
    """`alembic check` fails if a model changed without a migration. (The down/up round trip
    itself runs in the `owner_engine` fixture at the start of every session.)"""
    await asyncio.to_thread(command.check, alembic_config(settings.migration_database_url))


async def test_an_up_to_date_database_needs_no_backup(
    settings: "Settings", owner_engine: object
) -> None:
    import asyncio

    current = await asyncio.to_thread(migrate.current_revision, settings.migration_database_url)
    assert current == migrate.head_revision()
    assert await asyncio.to_thread(migrate.needs_backup, settings.migration_database_url) is False
