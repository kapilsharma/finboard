import asyncio

from alembic import command
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.core.config import Settings
from finboard.db.migrate import alembic_config


async def test_models_and_migrations_agree(settings: Settings, owner_engine: AsyncEngine) -> None:
    """`alembic check` fails if a model changed without a migration. (The down/up round trip
    itself runs in the `owner_engine` fixture at the start of every session.)"""
    await asyncio.to_thread(command.check, alembic_config(settings.migration_database_url))
