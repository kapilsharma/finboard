"""Application settings, read from `FINBOARD_*` environment variables (and `.env` in dev)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Mode(StrEnum):
    LOCAL = "local"  # one user on their own machine (v1)
    SERVER = "server"  # hosted, many users — needs a real auth backend (ADR-0021)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINBOARD_", env_file=(".env", "../.env"), extra="ignore"
    )

    mode: Mode = Mode.LOCAL
    env: Literal["dev", "test", "prod"] = "dev"

    host: str = "127.0.0.1"
    port: int = 8765
    allowed_hosts: list[str] = ["127.0.0.1", "localhost", "::1"]

    # Runtime role (subject to RLS) and migration role (table owner). See ADR-0025.
    database_url: str = (
        "postgresql+asyncpg://finboard_app:finboard_app_dev@127.0.0.1:55432/finboard"
    )
    migration_database_url: str = (
        "postgresql+asyncpg://finboard_owner:finboard_owner_dev@127.0.0.1:55432/finboard"
    )
    db_pool_size: int = 10
    db_max_overflow: int = 10

    redis_url: str = "redis://127.0.0.1:56379/0"

    log_level: str = "INFO"
    log_json: bool = True

    # Built SPA. When unset, the packaged `finboard/web/static` is used if present.
    static_dir: Path | None = None

    # Encrypts statement passwords on their way to the worker (ADR-0027). `finboard init`
    # writes one to .env. Without it, encrypted statements can't be unlocked.
    secret_key: SecretStr | None = None

    # Uploaded statements, still bank-encrypted (ADR-0026). Relative paths resolve against
    # the working directory, which is backend/ for `finboard dev`.
    blob_dir: Path = Path(".devdata/blobs")
    # `finboard serve` writes a pg_dump here before it migrates an older schema (§16).
    backup_dir: Path = Path(".devdata/backups")
    backup_before_migrate: bool = True

    # Import limits (ARCHITECTURE §7).
    max_upload_bytes: int = 20 * 1024 * 1024
    max_pages: int = 200
    parse_concurrency_per_user: int = 2
    parse_soft_time_limit: int = 60
    parse_time_limit: int = 75
    staged_import_ttl_days: int = 7
    # Extra parsers as `module:attr`, loaded next to the entry points (local development of an
    # adapter without packaging it, and tests).
    extra_parsers: list[str] = []

    # Optional AI (ARCHITECTURE §18, ADR-0030). The operator makes a feature *available*; each
    # user still opts in under Settings > AI. Both off by default.
    ai_suggestions: bool = False
    ai_suggest_method: Literal["auto", "embedding", "trigram"] = "auto"
    embed_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    model_dir: Path = Path(".devdata/models")
    ai_ask: Literal["off", "gemini", "ollama"] = "off"
    ai_ask_sql: bool = False  # the SQL fallback path (OQ-34)
    ai_model: str = "gemini-2.5-flash"
    gemini_api_key: SecretStr | None = None
    ollama_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2:3b"
    ai_timeout_seconds: float = 30.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
