import uuid

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, SessionTransaction

from finboard.core.config import Settings

RLS_USER_KEY = "user_id"


def create_engine(settings: Settings, *, url: str | None = None) -> AsyncEngine:
    return create_async_engine(
        url or settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
    )


def create_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False, autoflush=False)


@event.listens_for(Session, "after_begin")
def _set_rls_user(session: Session, _tx: SessionTransaction, connection: Connection) -> None:
    """Tell Postgres who the current user is, for every transaction the session opens.

    `set_config(..., is_local => true)` lasts until the transaction ends, so a pooled connection
    never carries one user's identity into another request (and it is PgBouncer-safe).
    """
    user_id: uuid.UUID | None = session.info.get(RLS_USER_KEY)
    if user_id is not None:
        connection.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)}
        )
