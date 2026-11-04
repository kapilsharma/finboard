"""Unit of Work: one AsyncSession = one transaction, plus the repositories bound to it.

Services commit explicitly (they own the transaction boundary). Leaving the context without
committing rolls back.
"""

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from finboard.db.engine import RLS_USER_KEY
from finboard.db.repos import (
    AccountRepo,
    CategoryRepo,
    ImportRepo,
    ImportRowRepo,
    JobRepo,
    RuleRepo,
    SettingRepo,
    StagedRowRepo,
    TransferRepo,
    TxnRepo,
    UserRepo,
)


class UnitOfWork:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID | None) -> None:
        self.session = session
        self.users = UserRepo(session)
        self._user_id = user_id

    @property
    def user_id(self) -> uuid.UUID:
        if self._user_id is None:
            raise RuntimeError("this unit of work is not bound to a user")
        return self._user_id

    async def bind_user(self, user_id: uuid.UUID) -> None:
        """Switch the RLS identity inside the current transaction (used when provisioning)."""
        self._user_id = user_id
        self.session.info[RLS_USER_KEY] = user_id
        await self.session.execute(
            text("SELECT set_config('app.user_id', :user_id, true)"), {"user_id": str(user_id)}
        )

    @property
    def accounts(self) -> AccountRepo:
        return AccountRepo(self.session, self.user_id)

    @property
    def categories(self) -> CategoryRepo:
        return CategoryRepo(self.session, self.user_id)

    @property
    def jobs(self) -> JobRepo:
        return JobRepo(self.session, self.user_id)

    @property
    def settings(self) -> SettingRepo:
        return SettingRepo(self.session, self.user_id)

    @property
    def imports(self) -> ImportRepo:
        return ImportRepo(self.session, self.user_id)

    @property
    def staged_rows(self) -> StagedRowRepo:
        return StagedRowRepo(self.session, self.user_id)

    @property
    def txns(self) -> TxnRepo:
        return TxnRepo(self.session, self.user_id)

    @property
    def import_rows(self) -> ImportRowRepo:
        return ImportRowRepo(self.session, self.user_id)

    @property
    def rules(self) -> RuleRepo:
        return RuleRepo(self.session, self.user_id)

    @property
    def transfers(self) -> TransferRepo:
        return TransferRepo(self.session, self.user_id)

    async def commit(self) -> None:
        await self.session.commit()

    async def rollback(self) -> None:
        await self.session.rollback()


@asynccontextmanager
async def unit_of_work(
    sessionmaker: async_sessionmaker[AsyncSession], user_id: uuid.UUID | None = None
) -> AsyncIterator[UnitOfWork]:
    async with sessionmaker() as session:
        session.info[RLS_USER_KEY] = user_id
        yield UnitOfWork(session, user_id)
