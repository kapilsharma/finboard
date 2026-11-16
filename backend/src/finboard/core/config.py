"""Application settings, read from `FINBOARD_*` environment variables (and `.env` in dev)."""

from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


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

    # ---- Server mode (FINBOARD_MODE=server, ADR-0041). None of this applies in local mode.
    # Where users reach Finboard, e.g. https://finboard.example.com. Required in server mode:
    # its host joins the Host allow-list, and https turns the session cookie's Secure flag on.
    public_url: str | None = None
    # `open` lets anyone who can reach the server create an account. `closed`: the operator
    # creates accounts with `finboard create-user`.
    signup: Literal["open", "closed"] = "closed"
    session_idle_days: int = 7  # a session unused for this long ends
    session_max_days: int = 30  # and no session outlives this, used or not
    # Wrong passwords before sign-in is refused for the rest of the window.
    login_max_failures: int = 5
    login_max_failures_per_ip: int = 30
    login_window_seconds: int = 15 * 60
    signup_per_ip_per_hour: int = 5
    # Per signed-in user. 0 switches a limit off.
    rate_limit_per_minute: int = 600
    upload_rate_per_hour: int = 60
    storage_quota_bytes: int = 5 * 1024**3  # stored statements
    # Addresses whose X-Forwarded-For is trusted (the TLS proxy), comma-separated, or `*`.
    forwarded_allow_ips: str = "127.0.0.1"

    # ---- Blob storage (ADR-0026). `s3` needs the `s3` extra and works with any S3-compatible
    # store. Credentials: these two, or the usual AWS environment / instance role.
    blob_backend: Literal["local", "s3"] = "local"
    s3_bucket: str | None = None
    s3_prefix: str = ""
    s3_endpoint_url: str | None = None
    s3_region: str | None = None
    s3_access_key_id: str | None = None
    s3_secret_access_key: SecretStr | None = None

    @property
    def is_server(self) -> bool:
        return self.mode is Mode.SERVER

    @property
    def cookie_secure(self) -> bool:
        return (self.public_url or "").lower().startswith("https://")

    def server_mode_problem(self) -> str | None:
        """Why this configuration can't run in server mode, or None when it can."""
        if not self.public_url:
            return (
                "FINBOARD_MODE=server needs FINBOARD_PUBLIC_URL, the address users open "
                "(for example https://finboard.example.com)."
            )
        parts = urlsplit(self.public_url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "FINBOARD_PUBLIC_URL must be an http(s) URL with a host."
        if parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS:
            return (
                "FINBOARD_PUBLIC_URL is plain http on a public host: passwords and session "
                "cookies would cross the network unencrypted. Put a TLS proxy in front and "
                "use https (docs/HOSTING.md)."
            )
        return None

    @property
    def effective_allowed_hosts(self) -> list[str]:
        hosts = list(self.allowed_hosts)
        if self.is_server and self.public_url:
            host = urlsplit(self.public_url).hostname
            if host and host not in hosts:
                hosts.append(host)
        return hosts


@lru_cache
def get_settings() -> Settings:
    return Settings()
