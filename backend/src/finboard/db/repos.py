"""Repositories: all SQL lives here.

User-scoped repositories filter every query by the caller's `user_id` and stamp it on every new
row. That is the application-level guard; Postgres RLS is the second, independent one.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from typing import Any

from sqlalchemy import delete, exists, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from finboard.db.models import (
    Account,
    AppUser,
    Category,
    ImportBatch,
    ImportRow,
    Job,
    StagedRow,
    Txn,
    UserSetting,
)
from finboard.domain.enums import ImportRowOutcome, ImportStatus


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

    async def bump_data_version(self, user_id: uuid.UUID) -> None:
        """Invalidate cached views of the user's financial data (dashboard ETag)."""
        await self.session.execute(
            update(AppUser)
            .where(AppUser.id == user_id)
            .values(data_version=AppUser.data_version + 1)
        )


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

    async def has_transactions(self, account_id: uuid.UUID) -> bool:
        stmt = select(exists().where(Txn.user_id == self.user_id, Txn.account_id == account_id))
        return bool(await self.session.scalar(stmt))

    async def by_masked_number(self, masked_number: str) -> Sequence[Account]:
        stmt = select(Account).where(
            Account.user_id == self.user_id,
            Account.active.is_(True),
            Account.masked_number == masked_number,
        )
        return (await self.session.scalars(stmt)).all()

    async def by_parser(self, parser_id: str) -> Sequence[Account]:
        stmt = select(Account).where(
            Account.user_id == self.user_id,
            Account.active.is_(True),
            Account.parser_id == parser_id,
        )
        return (await self.session.scalars(stmt)).all()


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

    async def in_use(self, category_id: uuid.UUID) -> bool:
        stmt = select(exists().where(Txn.user_id == self.user_id, Txn.category_id == category_id))
        return bool(await self.session.scalar(stmt))

    async def by_system_key(self, key: str) -> Category | None:
        stmt = select(Category).where(Category.user_id == self.user_id, Category.system_key == key)
        return (await self.session.execute(stmt)).scalar_one_or_none()


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


# ---------------------------------------------------------------- imports (ARCHITECTURE §7)


class ImportRepo(_UserScoped):
    async def get(self, import_id: uuid.UUID, *, for_update: bool = False) -> ImportBatch | None:
        stmt = select(ImportBatch).where(
            ImportBatch.user_id == self.user_id, ImportBatch.id == import_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, batch: ImportBatch) -> ImportBatch:
        batch.user_id = self.user_id
        self.session.add(batch)
        await self.session.flush()
        return batch

    async def list(
        self, *, statuses: Sequence[ImportStatus] | None, before: uuid.UUID | None, limit: int
    ) -> Sequence[ImportBatch]:
        """Newest first. Ids are UUIDv7 (time-ordered), so the id is the keyset cursor."""
        stmt = select(ImportBatch).where(ImportBatch.user_id == self.user_id)
        if statuses:
            stmt = stmt.where(ImportBatch.status.in_(statuses))
        if before is not None:
            stmt = stmt.where(ImportBatch.id < before)
        stmt = stmt.order_by(ImportBatch.id.desc()).limit(limit)
        return (await self.session.scalars(stmt)).all()

    async def committed_with_sha256(
        self, sha256: str, *, exclude_id: uuid.UUID
    ) -> ImportBatch | None:
        stmt = (
            select(ImportBatch)
            .where(
                ImportBatch.user_id == self.user_id,
                ImportBatch.file_sha256 == sha256,
                ImportBatch.status == ImportStatus.COMMITTED,
                ImportBatch.id != exclude_id,
            )
            .order_by(ImportBatch.committed_at)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def count_in_flight(self) -> int:
        stmt = select(func.count()).where(
            ImportBatch.user_id == self.user_id,
            ImportBatch.status.in_((ImportStatus.QUEUED, ImportStatus.PROCESSING)),
        )
        return int(await self.session.scalar(stmt) or 0)

    async def oldest_waiting(self) -> ImportBatch | None:
        stmt = (
            select(ImportBatch)
            .where(ImportBatch.user_id == self.user_id, ImportBatch.status == ImportStatus.UPLOADED)
            .order_by(ImportBatch.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_job(self, job_id: uuid.UUID, *, for_update: bool = False) -> ImportBatch | None:
        stmt = select(ImportBatch).where(
            ImportBatch.user_id == self.user_id, ImportBatch.job_id == job_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def lock_parse_slots(self) -> None:
        """Serialise "is there a free parse slot?" decisions for this user (transaction-scoped)."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('finboard:parse:' || :u, 0))"),
            {"u": str(self.user_id)},
        )

    async def lock_ledger(self, *, exclusive: bool) -> None:
        """Commits share this lock and run in parallel (the unique fingerprint index keeps them
        correct); a rollback takes it exclusively so it never races a commit that is about to
        record the same rows."""
        fn = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
        await self.session.execute(
            text(f"SELECT {fn}(hashtextextended('finboard:ledger:' || :u, 0))"),
            {"u": str(self.user_id)},
        )


class StagedRowRepo(_UserScoped):
    async def list(self, import_id: uuid.UUID) -> Sequence[StagedRow]:
        stmt = (
            select(StagedRow)
            .where(StagedRow.user_id == self.user_id, StagedRow.import_id == import_id)
            .order_by(StagedRow.seq)
        )
        return (await self.session.scalars(stmt)).all()

    async def get(self, import_id: uuid.UUID, seq: int) -> StagedRow | None:
        stmt = select(StagedRow).where(
            StagedRow.user_id == self.user_id,
            StagedRow.import_id == import_id,
            StagedRow.seq == seq,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def replace(self, import_id: uuid.UUID, rows: Sequence[StagedRow]) -> None:
        await self.delete_all(import_id)
        for row in rows:
            row.user_id = self.user_id
            row.import_id = import_id
        self.session.add_all(rows)
        await self.session.flush()

    async def delete_all(self, import_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(StagedRow).where(
                StagedRow.user_id == self.user_id, StagedRow.import_id == import_id
            )
        )


class TxnRepo(_UserScoped):
    async def ids_by_fingerprint(self, fingerprints: Iterable[str]) -> dict[str, uuid.UUID]:
        wanted = list(fingerprints)
        if not wanted:
            return {}
        stmt = select(Txn.fingerprint, Txn.id).where(
            Txn.user_id == self.user_id, Txn.fingerprint.in_(wanted)
        )
        return {fp: txn_id for fp, txn_id in (await self.session.execute(stmt)).all()}

    async def money_keys(
        self, account_id: uuid.UUID, start: date, end: date
    ) -> Sequence[tuple[date, str, Any, str]]:
        """(date, direction, amount, description_raw) of the account's rows in a date range."""
        stmt = select(Txn.date, Txn.direction, Txn.amount, Txn.description_raw).where(
            Txn.user_id == self.user_id,
            Txn.account_id == account_id,
            Txn.date >= start,
            Txn.date <= end,
        )
        return [
            (d, str(dr), amt, txt) for d, dr, amt, txt in (await self.session.execute(stmt)).all()
        ]

    async def insert_new(self, rows: Sequence[Mapping[str, Any]]) -> dict[str, uuid.UUID]:
        """INSERT … ON CONFLICT (user_id, fingerprint) DO NOTHING. Returns the rows actually
        inserted as {fingerprint: id}; conflicts (already imported) are simply absent."""
        if not rows:
            return {}
        values = [{**row, "user_id": self.user_id} for row in rows]
        stmt = (
            insert(Txn)
            .values(values)
            .on_conflict_do_nothing(index_elements=[Txn.user_id, Txn.fingerprint])
            .returning(Txn.fingerprint, Txn.id)
        )
        return {fp: txn_id for fp, txn_id in (await self.session.execute(stmt)).all()}

    async def delete_ids(self, ids: Sequence[uuid.UUID]) -> None:
        if ids:
            await self.session.execute(
                delete(Txn).where(Txn.user_id == self.user_id, Txn.id.in_(ids))
            )

    async def reassign(self, txn_id: uuid.UUID, import_id: uuid.UUID) -> None:
        await self.session.execute(
            update(Txn)
            .where(Txn.user_id == self.user_id, Txn.id == txn_id)
            .values(import_id=import_id)
        )


class ImportRowRepo(_UserScoped):
    async def add_all(
        self, import_id: uuid.UUID, rows: Sequence[tuple[str, uuid.UUID, str]]
    ) -> None:
        """rows: (fingerprint, txn_id, outcome)."""
        if not rows:
            return
        stmt = insert(ImportRow).values(
            [
                {
                    "user_id": self.user_id,
                    "import_id": import_id,
                    "fingerprint": fp,
                    "txn_id": txn_id,
                    "outcome": outcome,
                }
                for fp, txn_id, outcome in rows
            ]
        )
        await self.session.execute(stmt.on_conflict_do_nothing())

    async def inserted_by(self, import_id: uuid.UUID) -> Sequence[tuple[str, uuid.UUID]]:
        stmt = select(ImportRow.fingerprint, ImportRow.txn_id).where(
            ImportRow.user_id == self.user_id,
            ImportRow.import_id == import_id,
            ImportRow.outcome == ImportRowOutcome.INSERTED,
        )
        return [(fp, txn_id) for fp, txn_id in (await self.session.execute(stmt)).all()]

    async def heirs(
        self, import_id: uuid.UUID, fingerprints: Sequence[str]
    ) -> dict[str, uuid.UUID]:
        """For each fingerprint, the earliest *other* committed import that also saw it."""
        if not fingerprints:
            return {}
        stmt = (
            select(ImportRow.fingerprint, ImportRow.import_id)
            .join(
                ImportBatch,
                (ImportBatch.user_id == ImportRow.user_id)
                & (ImportBatch.id == ImportRow.import_id),
            )
            .where(
                ImportRow.user_id == self.user_id,
                ImportRow.import_id != import_id,
                ImportRow.fingerprint.in_(fingerprints),
                ImportBatch.status == ImportStatus.COMMITTED,
            )
            .order_by(ImportRow.fingerprint, ImportBatch.committed_at, ImportBatch.id)
            .distinct(ImportRow.fingerprint)
        )
        return {fp: heir for fp, heir in (await self.session.execute(stmt)).all()}

    async def mark_inserted(self, import_id: uuid.UUID, fingerprint: str) -> None:
        await self.session.execute(
            update(ImportRow)
            .where(
                ImportRow.user_id == self.user_id,
                ImportRow.import_id == import_id,
                ImportRow.fingerprint == fingerprint,
            )
            .values(outcome=ImportRowOutcome.INSERTED)
        )

    async def delete_all(self, import_id: uuid.UUID) -> None:
        await self.session.execute(
            delete(ImportRow).where(
                ImportRow.user_id == self.user_id, ImportRow.import_id == import_id
            )
        )
