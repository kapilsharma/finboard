"""Run Alembic programmatically (used by the CLI and tests), without needing alembic.ini.

Also the pre-migration backup (ARCHITECTURE §16): before an older schema is migrated,
`finboard serve` writes a `pg_dump` of the database to the backups directory.
"""

import asyncio
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

log = structlog.get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url)
    return config


def upgrade(database_url: str | None = None, revision: str = "head") -> None:
    command.upgrade(alembic_config(database_url), revision)


def downgrade(database_url: str | None = None, revision: str = "base") -> None:
    command.downgrade(alembic_config(database_url), revision)


class BackupFailed(RuntimeError):
    pass


def head_revision() -> str | None:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(database_url: str) -> str | None:
    """The database's revision, or None for a database Finboard hasn't migrated yet."""

    async def read() -> str | None:
        engine = create_async_engine(database_url)
        try:
            async with engine.connect() as conn:
                exists = await conn.scalar(
                    text("SELECT to_regclass('alembic_version') IS NOT NULL")
                )
                if not exists:
                    return None
                value = await conn.scalar(text("SELECT version_num FROM alembic_version"))
                return str(value) if value else None
        finally:
            await engine.dispose()

    return asyncio.run(read())


def needs_backup(database_url: str) -> bool:
    """True when there is data at an older revision (a fresh database needs no backup)."""
    current = current_revision(database_url)
    return current is not None and current != head_revision()


def backup(database_url: str, backup_dir: Path, *, revision: str | None = None) -> Path | None:
    """`pg_dump -Fc` of the database into `backup_dir`. The password goes in PGPASSWORD,
    never on the command line. Returns None (with a warning) when pg_dump isn't installed;
    raises BackupFailed when it is but the dump fails, so nothing is migrated unbacked."""
    pg_dump = shutil.which("pg_dump")
    if pg_dump is None:
        log.warning("migrate.backup_skipped", reason="pg_dump not found")
        return None
    url = make_url(database_url)
    backup_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"{url.database}-{stamp}-{revision or 'unknown'}.dump"
    env = {**os.environ, "PGPASSWORD": url.password or ""}
    args = [
        pg_dump,
        "--format=custom",
        f"--file={target}",
        f"--host={url.host or 'localhost'}",
        f"--port={url.port or 5432}",
        f"--username={url.username or ''}",
        url.database or "",
    ]
    result = subprocess.run(args, env=env, capture_output=True, text=True, check=False)  # noqa: S603
    if result.returncode != 0:
        target.unlink(missing_ok=True)
        # pg_dump's message names the server and versions, never data.
        raise BackupFailed(
            result.stderr.strip().splitlines()[-1] if result.stderr else "pg_dump failed"
        )
    target.chmod(0o600)
    log.info("migrate.backup_written", path=str(target))
    return target
