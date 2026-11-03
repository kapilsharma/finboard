"""Repositories: all SQL lives here.

User-scoped repositories filter every query by the caller's `user_id` and stamp it on every new
row. That is the application-level guard; Postgres RLS is the second, independent one.
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from finboard.db.models import Account, AppUser, Category, Job, UserSetting


class UserRepo:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, user_id: uuid.UUID) -> AppUser | None:
        return await self.session.get(AppUser, user_id)

    async def get_by_username(self, username: str) -> AppUser | None:
        result = await self.session.execute(select(AppUser).where(AppUser.username == username))
        return result.scalar_one_or_none()

    async def add(self, user: AppUser) -> AppUser:
        self.session.add(user)
        await self.session.flush()
        return user


class _UserScoped:
    def __init__(self, session: AsyncSession, user_id: uuid.UUID) -> None:
        self.session = session
        self.user_id = user_id


class AccountRepo(_UserScoped):
    async def list(self) -> Sequence[Account]:
        stmt = (
            select(Account)
            .where(Account.user_id == self.user_id)
            .order_by(Account.active.desc(), func.lower(Account.name))
        )
        return (await self.session.scalars(stmt)).all()

    async def get(self, account_id: uuid.UUID) -> Account | None:
        stmt = select(Account).where(Account.user_id == self.user_id, Account.id == account_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def name_taken(self, name: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        conditions = [Account.user_id == self.user_id, func.lower(Account.name) == name.lower()]
        if exclude_id is not None:
            conditions.append(Account.id != exclude_id)
        return bool(await self.session.scalar(select(exists().where(*conditions))))

    async def add(self, account: Account) -> Account:
        account.user_id = self.user_id
        self.session.add(account)
        await self.session.flush()
        return account

    async def delete(self, account: Account) -> None:
        await self.session.delete(account)
        await self.session.flush()


class CategoryRepo(_UserScoped):
    async def list(self) -> Sequence[Category]:
        stmt = (
            select(Category)
            .where(Category.user_id == self.user_id)
            .order_by(Category.sort_order, func.lower(Category.name))
        )
        return (await self.session.scalars(stmt)).all()

    async def get(self, category_id: uuid.UUID) -> Category | None:
        stmt = select(Category).where(Category.user_id == self.user_id, Category.id == category_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def name_taken(
        self, name: str, parent_id: uuid.UUID | None, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        conditions = [
            Category.user_id == self.user_id,
            Category.parent_id.is_(None) if parent_id is None else Category.parent_id == parent_id,
            func.lower(Category.name) == name.lower(),
        ]
        if exclude_id is not None:
            conditions.append(Category.id != exclude_id)
        return bool(await self.session.scalar(select(exists().where(*conditions))))

    async def has_children(self, category_id: uuid.UUID) -> bool:
        stmt = select(
            exists().where(Category.user_id == self.user_id, Category.parent_id == category_id)
        )
        return bool(await self.session.scalar(stmt))

    async def add(self, category: Category) -> Category:
        category.user_id = self.user_id
        self.session.add(category)
        await self.session.flush()
        return category

    async def add_all(self, categories: Sequence[Category]) -> None:
        for category in categories:
            category.user_id = self.user_id
        self.session.add_all(categories)
        await self.session.flush()

    async def delete(self, category: Category) -> None:
        await self.session.delete(category)
        await self.session.flush()


class JobRepo(_UserScoped):
    async def get(self, job_id: uuid.UUID, *, for_update: bool = False) -> Job | None:
        stmt = select(Job).where(Job.user_id == self.user_id, Job.id == job_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_recent(self, limit: int = 50) -> Sequence[Job]:
        stmt = (
            select(Job)
            .where(Job.user_id == self.user_id)
            .order_by(Job.created_at.desc())
            .limit(limit)
        )
        return (await self.session.scalars(stmt)).all()

    async def add(self, job: Job) -> Job:
        job.user_id = self.user_id
        self.session.add(job)
        await self.session.flush()
        return job


class SettingRepo(_UserScoped):
    async def all(self) -> dict[str, Any]:
        stmt = select(UserSetting.key, UserSetting.value).where(UserSetting.user_id == self.user_id)
        return {key: value for key, value in (await self.session.execute(stmt)).all()}

    async def set(self, key: str, value: Any) -> None:
        stmt = insert(UserSetting).values(user_id=self.user_id, key=key, value=value)
        stmt = stmt.on_conflict_do_update(
            index_elements=[UserSetting.user_id, UserSetting.key], set_={"value": value}
        )
        await self.session.execute(stmt)
