"""Repositories: all SQL lives here.

User-scoped repositories filter every query by the caller's `user_id` and stamp it on every new
row. That is the application-level guard; Postgres RLS is the second, independent one.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import (
    Table,
    bindparam,
    delete,
    exists,
    func,
    or_,
    select,
    text,
    tuple_,
    update,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from finboard.db.base import Base
from finboard.db.models import (
    Account,
    AppUser,
    AskQuery,
    Budget,
    Category,
    DashboardWidget,
    ImportBatch,
    ImportRow,
    Job,
    Rule,
    StagedRow,
    TransferPair,
    Txn,
    UserParserSetting,
    UserSetting,
)
from finboard.domain.enums import (
    AccountType,
    CategorisedBy,
    CategoryType,
    Direction,
    ImportRowOutcome,
    ImportStatus,
    JobStatus,
    TransferStatus,
)
from finboard.domain.errors import QueryTimeout


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

    async def all_ids(self) -> list[uuid.UUID]:
        """Every user (app_user has no row-level security: it holds no financial data)."""
        return list((await self.session.scalars(select(AppUser.id).order_by(AppUser.id))).all())

    async def bump_data_version(self, user_id: uuid.UUID) -> None:
        """Invalidate cached views of the user's financial data (dashboard ETag)."""
        await self.session.execute(
            update(AppUser)
            .where(AppUser.id == user_id)
            .values(data_version=AppUser.data_version + 1)
        )


async def _executemany(session: AsyncSession, stmt: Any, params: list[dict[str, Any]]) -> None:
    """A Core executemany (UPDATE … WHERE id = :b_id per row). Run on the connection: passing a
    parameter list to `session.execute` with an ORM entity would mean ORM bulk-update-by-PK."""
    connection = await session.connection()
    await connection.execute(stmt, params)


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

    async def merge_into(self, source: uuid.UUID, target: Category) -> dict[str, int]:
        """Point everything at `source` to `target`: transactions (with the target's type),
        staged rows, rules and budget changes. Where both categories have a budget change for
        the same month, the target's wins. Returns counts moved."""
        u = self.user_id
        txns = await self.session.execute(
            update(Txn)
            .where(Txn.user_id == u, Txn.category_id == source)
            .values(category_id=target.id, type=target.type)
            .execution_options(synchronize_session=False)
        )
        await self.session.execute(
            update(StagedRow)
            .where(StagedRow.user_id == u, StagedRow.category_id == source)
            .values(category_id=target.id)
            .execution_options(synchronize_session=False)
        )
        rules = await self.session.execute(
            update(Rule)
            .where(Rule.user_id == u, Rule.category_id == source)
            .values(category_id=target.id)
            .execution_options(synchronize_session=False)
        )
        taken = select(Budget.effective_from).where(
            Budget.user_id == u, Budget.category_id == target.id
        )
        await self.session.execute(
            delete(Budget).where(
                Budget.user_id == u,
                Budget.category_id == source,
                Budget.effective_from.in_(taken.scalar_subquery()),
            )
        )
        budgets = await self.session.execute(
            update(Budget)
            .where(Budget.user_id == u, Budget.category_id == source)
            .values(category_id=target.id)
            .execution_options(synchronize_session=False)
        )
        return {
            "transactions": int(txns.rowcount or 0),  # type: ignore[attr-defined]
            "rules": int(rules.rowcount or 0),  # type: ignore[attr-defined]
            "budgets": int(budgets.rowcount or 0),  # type: ignore[attr-defined]
        }

    async def used_by_rules(self, category_id: uuid.UUID) -> bool:
        stmt = select(exists().where(Rule.user_id == self.user_id, Rule.category_id == category_id))
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

    async def stale_queued(self, before: datetime) -> list[Job]:
        stmt = select(Job).where(
            Job.user_id == self.user_id, Job.status == JobStatus.QUEUED, Job.created_at < before
        )
        return list((await self.session.scalars(stmt.with_for_update(skip_locked=True))).all())

    async def finished_before(self, before: datetime) -> list[Job]:
        stmt = select(Job).where(
            Job.user_id == self.user_id,
            Job.status.in_((JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED)),
            Job.finished_at < before,
        )
        return list((await self.session.scalars(stmt)).all())

    async def delete_ids(self, ids: Sequence[uuid.UUID]) -> None:
        if ids:
            await self.session.execute(
                delete(Job).where(Job.user_id == self.user_id, Job.id.in_(ids))
            )

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

    async def expired(self, now: datetime) -> Sequence[ImportBatch]:
        """Staged imports past their expiry: never committed, not being worked on."""
        stmt = (
            select(ImportBatch)
            .where(
                ImportBatch.user_id == self.user_id,
                ImportBatch.expires_at < now,
                ImportBatch.status.in_(
                    (ImportStatus.PARSED, ImportStatus.NEEDS_PASSWORD, ImportStatus.FAILED)
                ),
            )
            .with_for_update(skip_locked=True)
        )
        return (await self.session.scalars(stmt)).all()

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


@dataclass(frozen=True, slots=True)
class TxnFactsRow:
    """The columns categorisation and pairing need, without loading ORM objects."""

    id: uuid.UUID
    account_id: uuid.UUID
    account_type: AccountType
    date: date
    direction: Direction
    amount: Decimal
    description_raw: str
    description_norm: str
    category_id: uuid.UUID
    type: CategoryType
    categorised_by: CategorisedBy
    rule_id: uuid.UUID | None
    needs_review: bool


@dataclass(frozen=True, slots=True)
class TxnFilters:
    start: date | None = None
    end: date | None = None
    account_ids: Sequence[uuid.UUID] = ()
    category_ids: Sequence[uuid.UUID] = ()
    types: Sequence[CategoryType] = ()
    needs_review: bool | None = None
    q: str | None = None  # matched against description, account and category name
    q_norm: str | None = None  # the same text, normalised like descriptions are


@dataclass(frozen=True, slots=True)
class TxnListRow:
    txn: Txn
    account_name: str
    category_name: str
    sort_value: Any


def _like(text_: str) -> str:
    escaped = text_.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


class TxnRepo(_UserScoped):
    SORT_KEYS = ("date", "description", "account", "category", "type", "amount")

    def _sort_expr(self, key: str) -> Any:
        return {
            "date": Txn.date,
            "description": func.lower(Txn.description_raw),
            "account": func.lower(Account.name),
            "category": func.lower(Category.name),
            "type": Txn.type,
            "amount": Txn.amount,
        }[key]

    def _filtered(self, filters: TxnFilters) -> Any:
        stmt = (
            select(Txn)
            .join(Account, (Account.user_id == Txn.user_id) & (Account.id == Txn.account_id))
            .join(Category, (Category.user_id == Txn.user_id) & (Category.id == Txn.category_id))
            .where(Txn.user_id == self.user_id)
        )
        if filters.start is not None:
            stmt = stmt.where(Txn.date >= filters.start)
        if filters.end is not None:
            stmt = stmt.where(Txn.date <= filters.end)
        if filters.account_ids:
            stmt = stmt.where(Txn.account_id.in_(filters.account_ids))
        if filters.category_ids:
            stmt = stmt.where(Txn.category_id.in_(filters.category_ids))
        if filters.types:
            stmt = stmt.where(Txn.type.in_(filters.types))
        if filters.needs_review is not None:
            stmt = stmt.where(Txn.needs_review.is_(filters.needs_review))
        if filters.q:
            conditions = [
                Txn.description_raw.ilike(_like(filters.q), escape="\\"),
                Account.name.ilike(_like(filters.q), escape="\\"),
                Category.name.ilike(_like(filters.q), escape="\\"),
            ]
            if filters.q_norm:  # uses the trigram index on description_norm
                conditions.append(Txn.description_norm.ilike(_like(filters.q_norm), escape="\\"))
            stmt = stmt.where(or_(*conditions))
        return stmt

    async def page(
        self,
        filters: TxnFilters,
        *,
        sort: str,
        descending: bool,
        after: tuple[Any, uuid.UUID] | None,
        limit: int,
    ) -> list[TxnListRow]:
        """One page, keyset-paged on (sort value, id): stable under inserts, no OFFSET."""
        key = self._sort_expr(sort)
        stmt = self._filtered(filters).add_columns(Account.name, Category.name, key)
        if after is not None:
            position = tuple_(key, Txn.id)
            bound = tuple_(bindparam("after_v", after[0]), bindparam("after_id", after[1]))
            stmt = stmt.where(position < bound if descending else position > bound)
        order = (key.desc(), Txn.id.desc()) if descending else (key.asc(), Txn.id.asc())
        stmt = stmt.order_by(*order).limit(limit)
        result = await self.session.execute(stmt)
        return [TxnListRow(t, a, c, v) for t, a, c, v in result.all()]

    async def filtered_sums(
        self, filters: TxnFilters
    ) -> list[tuple[CategoryType, Direction, Decimal, int]]:
        """(type, direction, Σ amount, count) over every row the filters match."""
        sub = self._filtered(filters).subquery()
        stmt = select(sub.c.type, sub.c.direction, func.sum(sub.c.amount), func.count()).group_by(
            sub.c.type, sub.c.direction
        )
        return [(t, d, amount, int(n)) for t, d, amount, n in await self.session.execute(stmt)]

    async def get(self, txn_id: uuid.UUID, *, for_update: bool = False) -> Txn | None:
        stmt = select(Txn).where(Txn.user_id == self.user_id, Txn.id == txn_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_many(self, ids: Sequence[uuid.UUID], *, for_update: bool = False) -> list[Txn]:
        if not ids:
            return []
        stmt = select(Txn).where(Txn.user_id == self.user_id, Txn.id.in_(ids)).order_by(Txn.id)
        if for_update:
            stmt = stmt.with_for_update()
        return list((await self.session.scalars(stmt)).all())

    async def facts(
        self,
        *,
        categorised_by: Sequence[CategorisedBy] | None = None,
        ids: Sequence[uuid.UUID] | None = None,
        exclude_paired: bool = False,
        since: date | None = None,
    ) -> list[TxnFactsRow]:
        stmt = select(
            Txn.id,
            Txn.account_id,
            Account.type,
            Txn.date,
            Txn.direction,
            Txn.amount,
            Txn.description_raw,
            Txn.description_norm,
            Txn.category_id,
            Txn.type,
            Txn.categorised_by,
            Txn.rule_id,
            Txn.needs_review,
        ).join(Account, (Account.user_id == Txn.user_id) & (Account.id == Txn.account_id))
        stmt = stmt.where(Txn.user_id == self.user_id)
        if categorised_by is not None:
            stmt = stmt.where(Txn.categorised_by.in_(categorised_by))
        if ids is not None:
            stmt = stmt.where(Txn.id.in_(ids))
        if since is not None:
            stmt = stmt.where(Txn.date >= since)
        if exclude_paired:
            active = select(TransferPair.debit_txn_id, TransferPair.credit_txn_id).where(
                TransferPair.user_id == self.user_id,
                TransferPair.status != TransferStatus.REJECTED,
            )
            sub = active.subquery()
            stmt = stmt.where(
                ~exists().where(or_(sub.c.debit_txn_id == Txn.id, sub.c.credit_txn_id == Txn.id))
            )
        stmt = stmt.order_by(Txn.date, Txn.id)
        return [TxnFactsRow(*row) for row in (await self.session.execute(stmt)).all()]

    async def set_categories(self, changes: Sequence[Mapping[str, Any]]) -> None:
        """Bulk update by id. Each change has id, category_id, type, categorised_by, rule_id,
        needs_review and description_norm. One UPDATE … FROM unnest(arrays) statement: far
        faster than a statement per row (the 50k re-apply budget, ARCHITECTURE §14)."""
        if not changes:
            return
        stmt = text(
            """
            UPDATE txn AS t
            SET category_id = v.category_id, type = v.type, categorised_by = v.categorised_by,
                rule_id = v.rule_id, needs_review = v.needs_review,
                description_norm = v.description_norm, updated_at = now()
            FROM unnest(
                CAST(:ids AS uuid[]), CAST(:category_ids AS uuid[]), CAST(:types AS text[]),
                CAST(:categorised_by AS text[]), CAST(:rule_ids AS uuid[]),
                CAST(:needs_review AS boolean[]), CAST(:norms AS text[])
            ) AS v(id, category_id, type, categorised_by, rule_id, needs_review, description_norm)
            WHERE t.user_id = :user_id AND t.id = v.id
            """
        )
        await self.session.execute(
            stmt,
            {
                "user_id": self.user_id,
                "ids": [c["id"] for c in changes],
                "category_ids": [c["category_id"] for c in changes],
                "types": [str(c["type"]) for c in changes],
                "categorised_by": [str(c["categorised_by"]) for c in changes],
                "rule_ids": [c["rule_id"] for c in changes],
                "needs_review": [bool(c["needs_review"]) for c in changes],
                "norms": [c["description_norm"] for c in changes],
            },
        )

    async def set_type_for_category(self, category_id: uuid.UUID, type_: CategoryType) -> int:
        result = await self.session.execute(
            update(Txn)
            .where(Txn.user_id == self.user_id, Txn.category_id == category_id)
            .values(type=type_)
            .execution_options(synchronize_session=False)
        )
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def needing_review(
        self, *, start: date | None = None, end: date | None = None, limit: int = 2000
    ) -> list[Txn]:
        stmt = select(Txn).where(Txn.user_id == self.user_id, Txn.needs_review.is_(True))
        if start is not None:
            stmt = stmt.where(Txn.date >= start)
        if end is not None:
            stmt = stmt.where(Txn.date <= end)
        stmt = stmt.order_by(Txn.date.desc(), Txn.id).limit(limit)
        return list((await self.session.scalars(stmt)).all())

    async def count_needing_review(self) -> int:
        stmt = select(func.count()).where(Txn.user_id == self.user_id, Txn.needs_review.is_(True))
        return int(await self.session.scalar(stmt) or 0)

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


# ---------------------------------------------------------------- categorisation (ARCHITECTURE §9)


class RuleRepo(_UserScoped):
    async def list(self, *, enabled_only: bool = False) -> list[Rule]:
        stmt = select(Rule).where(Rule.user_id == self.user_id)
        if enabled_only:
            stmt = stmt.where(Rule.enabled.is_(True))
        stmt = stmt.order_by(Rule.priority, Rule.id)
        return list((await self.session.scalars(stmt)).all())

    async def get(self, rule_id: uuid.UUID, *, for_update: bool = False) -> Rule | None:
        stmt = select(Rule).where(Rule.user_id == self.user_id, Rule.id == rule_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, rule: Rule) -> Rule:
        rule.user_id = self.user_id
        self.session.add(rule)
        await self.session.flush()
        return rule

    async def add_all(self, rules: Sequence[Rule]) -> None:
        for rule in rules:
            rule.user_id = self.user_id
        self.session.add_all(rules)
        await self.session.flush()

    async def delete(self, rule: Rule) -> None:
        await self.session.delete(rule)
        await self.session.flush()

    async def delete_all(self) -> None:
        await self.session.execute(delete(Rule).where(Rule.user_id == self.user_id))

    async def next_priority(self) -> int:
        stmt = select(func.max(Rule.priority)).where(Rule.user_id == self.user_id)
        current = await self.session.scalar(stmt)
        return 0 if current is None else int(current) + 1

    async def lock(self) -> None:
        """Serialise rule-order changes for this user (transaction-scoped)."""
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('finboard:rules:' || :u, 0))"),
            {"u": str(self.user_id)},
        )

    async def set_priorities(self, ordered_ids: Sequence[uuid.UUID]) -> None:
        if not ordered_ids:
            return
        stmt = (
            update(Rule)
            .where(Rule.user_id == self.user_id, Rule.id == bindparam("b_id"))
            .values(priority=bindparam("b_priority"))
            .execution_options(synchronize_session=False)
        )
        await _executemany(
            self.session,
            stmt,
            [{"b_id": rid, "b_priority": i} for i, rid in enumerate(ordered_ids)],
        )

    async def add_hits(self, hits: Mapping[uuid.UUID, int], at: datetime) -> None:
        if not hits:
            return
        stmt = (
            update(Rule)
            .where(Rule.user_id == self.user_id, Rule.id == bindparam("b_id"))
            .values(hits=Rule.hits + bindparam("b_hits"), last_hit_at=at)
            .execution_options(synchronize_session=False)
        )
        await _executemany(self.session, stmt, [{"b_id": k, "b_hits": v} for k, v in hits.items()])

    async def disable(self, rule_ids: Iterable[uuid.UUID], error: str) -> None:
        ids = list(rule_ids)
        if ids:
            await self.session.execute(
                update(Rule)
                .where(Rule.user_id == self.user_id, Rule.id.in_(ids))
                .values(enabled=False, error=error)
                .execution_options(synchronize_session=False)
            )


class TransferRepo(_UserScoped):
    async def list(self, status: TransferStatus | None) -> list[TransferPair]:
        stmt = select(TransferPair).where(TransferPair.user_id == self.user_id)
        if status is not None:
            stmt = stmt.where(TransferPair.status == status)
        stmt = stmt.order_by(TransferPair.created_at.desc(), TransferPair.id)
        return list((await self.session.scalars(stmt)).all())

    async def get(self, pair_id: uuid.UUID, *, for_update: bool = False) -> TransferPair | None:
        stmt = select(TransferPair).where(
            TransferPair.user_id == self.user_id, TransferPair.id == pair_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def active_for_txn(self, txn_id: uuid.UUID) -> TransferPair | None:
        stmt = select(TransferPair).where(
            TransferPair.user_id == self.user_id,
            TransferPair.status != TransferStatus.REJECTED,
            or_(TransferPair.debit_txn_id == txn_id, TransferPair.credit_txn_id == txn_id),
        )
        return (await self.session.execute(stmt.with_for_update())).scalar_one_or_none()

    async def rejected_keys(self) -> set[tuple[uuid.UUID, uuid.UUID]]:
        stmt = select(TransferPair.debit_txn_id, TransferPair.credit_txn_id).where(
            TransferPair.user_id == self.user_id, TransferPair.status == TransferStatus.REJECTED
        )
        return {(d, c) for d, c in (await self.session.execute(stmt)).all()}

    async def add_suggestions(self, pairs: Sequence[Mapping[str, Any]]) -> int:
        """Insert suggested pairs, skipping any that a concurrent run already added."""
        if not pairs:
            return 0
        stmt = (
            insert(TransferPair)
            .values(
                [
                    {**pair, "user_id": self.user_id, "status": TransferStatus.SUGGESTED}
                    for pair in pairs
                ]
            )
            .on_conflict_do_nothing()
            .returning(TransferPair.id)
        )
        return len((await self.session.execute(stmt)).all())

    async def count(self, status: TransferStatus) -> int:
        stmt = select(func.count()).where(
            TransferPair.user_id == self.user_id, TransferPair.status == status
        )
        return int(await self.session.scalar(stmt) or 0)


# ---------------------------------------------------------------- dashboard and budgets (§10, §12)


class BudgetRepo(_UserScoped):
    async def history(self, category_id: uuid.UUID | None = None) -> list[Budget]:
        """Every limit change, oldest first. Small (a few rows per category): the lookup for a
        month happens in `domain.budgets`."""
        stmt = select(Budget).where(Budget.user_id == self.user_id)
        if category_id is not None:
            stmt = stmt.where(Budget.category_id == category_id)
        stmt = stmt.order_by(Budget.category_id, Budget.effective_from)
        return list((await self.session.scalars(stmt)).all())

    async def delete_entry(self, category_id: uuid.UUID, effective_from: date) -> bool:
        result = await self.session.execute(
            delete(Budget).where(
                Budget.user_id == self.user_id,
                Budget.category_id == category_id,
                Budget.effective_from == effective_from,
            )
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]

    async def put(
        self, category_id: uuid.UUID, effective_from: date, limit: Decimal | None
    ) -> Budget:
        stmt = (
            insert(Budget)
            .values(
                user_id=self.user_id,
                category_id=category_id,
                effective_from=effective_from,
                monthly_limit=limit,
            )
            .on_conflict_do_update(
                index_elements=[Budget.user_id, Budget.category_id, Budget.effective_from],
                set_={"monthly_limit": limit, "updated_at": func.now()},
            )
            .returning(Budget)
        )
        budget = (await self.session.execute(stmt)).scalar_one()
        return budget


@dataclass(frozen=True, slots=True)
class GroupedSum:
    month: date
    type: CategoryType
    direction: Direction
    category_id: uuid.UUID
    account_id: uuid.UUID
    amount: Decimal


class DashboardRepo(_UserScoped):
    """The grouped SQL behind the dashboard. Every query is an index range scan on
    (user_id, date …) (ARCHITECTURE §12, §14)."""

    async def months(self) -> list[date]:
        """First day of every month that has transactions, newest first."""
        month = func.date_trunc("month", Txn.date)
        stmt = (
            select(month.label("m"))
            .where(Txn.user_id == self.user_id)
            .group_by(month)
            .order_by(month.desc())
        )
        return [
            m.date() if isinstance(m, datetime) else m for (m,) in await self.session.execute(stmt)
        ]

    async def grouped_sums(self, start: date, end: date) -> list[GroupedSum]:
        """SUM(amount) per month, type, direction, category and account, transfers left out."""
        month = func.date_trunc("month", Txn.date)
        stmt = (
            select(
                month.label("m"),
                Txn.type,
                Txn.direction,
                Txn.category_id,
                Txn.account_id,
                func.sum(Txn.amount),
            )
            .where(
                Txn.user_id == self.user_id,
                Txn.date >= start,
                Txn.date <= end,
                Txn.type != CategoryType.TRANSFER,
            )
            .group_by(month, Txn.type, Txn.direction, Txn.category_id, Txn.account_id)
        )
        return [
            GroupedSum(m.date() if isinstance(m, datetime) else m, t, d, c, a, amount)
            for m, t, d, c, a, amount in await self.session.execute(stmt)
        ]

    async def review_count(self, start: date, end: date) -> int:
        stmt = select(func.count()).where(
            Txn.user_id == self.user_id,
            Txn.needs_review.is_(True),
            Txn.date >= start,
            Txn.date <= end,
        )
        return int(await self.session.scalar(stmt) or 0)


class ParserSettingRepo(_UserScoped):
    async def all(self) -> dict[str, UserParserSetting]:
        stmt = select(UserParserSetting).where(UserParserSetting.user_id == self.user_id)
        return {s.parser_id: s for s in (await self.session.scalars(stmt)).all()}

    async def put(self, parser_id: str, *, enabled: bool, options: dict[str, Any]) -> None:
        stmt = insert(UserParserSetting).values(
            user_id=self.user_id, parser_id=parser_id, enabled=enabled, options=options
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[UserParserSetting.user_id, UserParserSetting.parser_id],
            set_={"enabled": enabled, "options": options, "updated_at": func.now()},
        )
        await self.session.execute(stmt)


# ---------------------------------------------------------------- data export / import / delete


def _table(model: type[Base]) -> Table:
    return cast(Table, model.__table__)


class DataRepo(_UserScoped):
    """Whole-table operations on one user's rows, for export, import and delete-all."""

    async def dump(self, model: type[Base]) -> list[dict[str, Any]]:
        table = _table(model)
        columns = [c for c in table.columns if c.name != "user_id"]
        order = [c for c in table.primary_key.columns if c.name != "user_id"]
        stmt = select(*columns).where(table.c.user_id == self.user_id).order_by(*order)
        return [dict(row._mapping) for row in await self.session.execute(stmt)]

    async def insert(self, model: type[Base], rows: Sequence[Mapping[str, Any]]) -> None:
        table = _table(model)
        for start in range(0, len(rows), 1000):
            chunk = [{**row, "user_id": self.user_id} for row in rows[start : start + 1000]]
            if chunk:
                await self.session.execute(insert(table).values(chunk))

    async def delete(self, model: type[Base], *, keep_ids: Sequence[uuid.UUID] = ()) -> int:
        table = _table(model)
        stmt = delete(table).where(table.c.user_id == self.user_id)
        if keep_ids:
            stmt = stmt.where(table.c.id.not_in(keep_ids))
        return int((await self.session.execute(stmt)).rowcount or 0)  # type: ignore[attr-defined]

    async def has_financial_data(self) -> bool:
        """Accounts, transactions or imports (categories and rules alone don't count)."""
        for model in (Account, Txn, ImportBatch):
            table = _table(model)
            found = await self.session.scalar(
                select(exists().where(table.c.user_id == self.user_id))
            )
            if found:
                return True
        return False


# ---------------------------------------------------------------- AI embeddings (M3a)


@dataclass(frozen=True, slots=True)
class NeighbourRow:
    txn_id: uuid.UUID
    category_id: uuid.UUID
    similarity: float
    date: date
    description: str
    amount: Decimal
    direction: Direction


class EmbeddingRepo(_UserScoped):
    async def to_embed(self, model: str, limit: int) -> list[tuple[uuid.UUID, str]]:
        """Transactions with no embedding from `model` yet (missing, or from another model)."""
        stmt = text(
            """
            SELECT t.id, t.description_norm FROM txn t
            LEFT JOIN txn_embedding e ON e.user_id = t.user_id AND e.txn_id = t.id
            WHERE t.user_id = :u AND (e.txn_id IS NULL OR e.model <> :m)
            ORDER BY t.id LIMIT :limit
            """
        )
        rows = await self.session.execute(stmt, {"u": self.user_id, "m": model, "limit": limit})
        return [(r[0], r[1]) for r in rows]

    async def upsert(self, model: str, rows: Sequence[tuple[uuid.UUID, list[float]]]) -> None:
        if not rows:
            return
        stmt = text(
            """
            INSERT INTO txn_embedding (user_id, txn_id, model, embedding)
            SELECT :u, x.txn_id, :m, CAST(x.vec AS vector)
            FROM unnest(CAST(:ids AS uuid[]), CAST(:vecs AS text[])) AS x(txn_id, vec)
            ON CONFLICT (user_id, txn_id)
            DO UPDATE SET model = EXCLUDED.model, embedding = EXCLUDED.embedding,
                          created_at = now()
            """
        )
        await self.session.execute(
            stmt,
            {
                "u": self.user_id,
                "m": model,
                "ids": [r[0] for r in rows],
                "vecs": ["[" + ",".join(repr(float(v)) for v in r[1]) + "]" for r in rows],
            },
        )

    async def counts(self, model: str) -> tuple[int, int]:
        """(transactions embedded with `model`, all transactions)."""
        stmt = text(
            """
            SELECT (SELECT count(*) FROM txn_embedding WHERE user_id = :u AND model = :m),
                   (SELECT count(*) FROM txn WHERE user_id = :u)
            """
        )
        done, total = (await self.session.execute(stmt, {"u": self.user_id, "m": model})).one()
        return int(done), int(total)

    async def has_embedding(self, txn_id: uuid.UUID, model: str) -> bool:
        stmt = text(
            "SELECT EXISTS (SELECT 1 FROM txn_embedding"
            " WHERE user_id = :u AND txn_id = :t AND model = :m)"
        )
        params = {"u": self.user_id, "t": txn_id, "m": model}
        return bool(await self.session.scalar(stmt, params))

    async def neighbours_by_embedding(
        self, txn_id: uuid.UUID, model: str, k: int
    ) -> list[NeighbourRow]:
        """The k nearest rule- or manually-categorised transactions in the same direction,
        by cosine similarity (exact scan; ADR-0031: no ANN index until perf needs one)."""
        stmt = text(
            """
            WITH q AS (
              SELECT e.embedding, t.direction FROM txn_embedding e
              JOIN txn t ON t.user_id = e.user_id AND t.id = e.txn_id
              WHERE e.user_id = :u AND e.txn_id = :t AND e.model = :m
            )
            SELECT n.id, n.category_id, 1 - (ne.embedding <=> q.embedding) AS similarity,
                   n.date, n.description_raw, n.amount, n.direction
            FROM q
            JOIN txn_embedding ne ON ne.user_id = :u AND ne.model = :m AND ne.txn_id <> :t
            JOIN txn n ON n.user_id = ne.user_id AND n.id = ne.txn_id
            WHERE n.categorised_by IN ('rule', 'manual') AND n.direction = q.direction
            ORDER BY ne.embedding <=> q.embedding
            LIMIT :k
            """
        )
        rows = await self.session.execute(
            stmt, {"u": self.user_id, "t": txn_id, "m": model, "k": k}
        )
        return [NeighbourRow(*r) for r in rows]

    async def neighbours_by_trigram(self, txn_id: uuid.UUID, k: int) -> list[NeighbourRow]:
        """The same, by pg_trgm similarity of normalised descriptions (the baseline)."""
        stmt = text(
            """
            WITH q AS (SELECT description_norm, direction FROM txn WHERE user_id = :u AND id = :t)
            SELECT n.id, n.category_id, similarity(n.description_norm, q.description_norm) AS s,
                   n.date, n.description_raw, n.amount, n.direction
            FROM q JOIN txn n ON n.user_id = :u AND n.id <> :t
            WHERE n.categorised_by IN ('rule', 'manual') AND n.direction = q.direction
            ORDER BY s DESC, n.id
            LIMIT :k
            """
        )
        rows = await self.session.execute(stmt, {"u": self.user_id, "t": txn_id, "k": k})
        return [NeighbourRow(r[0], r[1], float(r[2]), r[3], r[4], r[5], r[6]) for r in rows]


# ---------------------------------------------------------------- Ask Finboard (M4a, ADR-0032)


@dataclass(frozen=True, slots=True)
class AccountAliasRow:
    alias: str
    type: str
    institution: str | None


class AskRepo(_UserScoped):
    async def add(self, query: AskQuery) -> AskQuery:
        query.user_id = self.user_id
        self.session.add(query)
        await self.session.flush()
        return query

    async def get(self, query_id: uuid.UUID) -> AskQuery | None:
        stmt = select(AskQuery).where(AskQuery.user_id == self.user_id, AskQuery.id == query_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def history(self, limit: int = 50) -> Sequence[AskQuery]:
        stmt = (
            select(AskQuery)
            .where(AskQuery.user_id == self.user_id)
            .order_by(AskQuery.created_at.desc(), AskQuery.id.desc())
            .limit(limit)
        )
        return (await self.session.scalars(stmt)).all()

    async def delete_history(self) -> int:
        """Every question that isn't pinned to the dashboard."""
        pinned = select(DashboardWidget.ask_query_id).where(DashboardWidget.user_id == self.user_id)
        stmt = delete(AskQuery).where(AskQuery.user_id == self.user_id, AskQuery.id.not_in(pinned))
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)  # type: ignore[attr-defined]

    async def aliases(self) -> list[AccountAliasRow]:
        """Account aliases in the same order as the `ai_txn` view (created_at, id)."""
        stmt = (
            select(Account.type, Account.institution)
            .where(Account.user_id == self.user_id)
            .order_by(Account.created_at, Account.id)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            AccountAliasRow(
                f"Account {chr(65 + i)}" if i < 26 else f"Account {i + 1}",
                str(getattr(t, "value", t)),
                inst,
            )
            for i, (t, inst) in enumerate(rows)
        ]

    async def sandbox_rows(self) -> tuple[list[tuple[Any, ...]], list[tuple[Any, ...]]]:
        """The caller's rows from the views, for the SQLite sandbox (RLS applies)."""
        txns = await self.session.execute(
            text(
                "SELECT date, month, account, account_type, category, parent_category, type,"
                " direction, signed_amount, merchant FROM ai_txn ORDER BY date"
            )
        )
        budgets = await self.session.execute(
            text("SELECT month, category, monthly_limit FROM ai_budget ORDER BY month")
        )
        return [tuple(r) for r in txns], [tuple(r) for r in budgets]

    async def run_read_only(
        self, sql: str, params: Mapping[str, Any], *, timeout_ms: int
    ) -> list[tuple[Any, ...]]:
        """Builder SQL (never model SQL) on its own connection: a READ ONLY transaction, bound
        to this user for RLS, with a statement timeout."""
        engine = self.session.bind
        assert isinstance(engine, AsyncEngine)  # sessions are bound to the app engine
        async with engine.connect() as conn:
            await conn.execute(text("SET TRANSACTION READ ONLY"))
            await conn.execute(
                text("SELECT set_config('app.user_id', :u, true)"), {"u": str(self.user_id)}
            )
            await conn.execute(text(f"SET LOCAL statement_timeout = {int(timeout_ms)}"))
            try:
                rows = await conn.execute(text(sql), dict(params))
            except DBAPIError as exc:
                if getattr(exc.orig, "sqlstate", None) == "57014":  # query_canceled
                    raise QueryTimeout() from None
                raise
            result = [tuple(r) for r in rows]
            await conn.rollback()
        return result

    async def add_widget(self, widget: DashboardWidget) -> DashboardWidget:
        widget.user_id = self.user_id
        stmt = select(func.coalesce(func.max(DashboardWidget.sort_order), -1)).where(
            DashboardWidget.user_id == self.user_id
        )
        widget.sort_order = int((await self.session.execute(stmt)).scalar_one()) + 1
        self.session.add(widget)
        await self.session.flush()
        return widget

    async def widget_for(self, query_id: uuid.UUID) -> DashboardWidget | None:
        stmt = select(DashboardWidget).where(
            DashboardWidget.user_id == self.user_id, DashboardWidget.ask_query_id == query_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def widgets(self) -> list[tuple[DashboardWidget, AskQuery]]:
        stmt = (
            select(DashboardWidget, AskQuery)
            .join(
                AskQuery,
                (AskQuery.user_id == DashboardWidget.user_id)
                & (AskQuery.id == DashboardWidget.ask_query_id),
            )
            .where(DashboardWidget.user_id == self.user_id)
            .order_by(DashboardWidget.sort_order, DashboardWidget.created_at)
        )
        return [(w, q) for w, q in (await self.session.execute(stmt)).all()]

    async def delete_widget(self, widget_id: uuid.UUID) -> bool:
        stmt = delete(DashboardWidget).where(
            DashboardWidget.user_id == self.user_id, DashboardWidget.id == widget_id
        )
        return bool((await self.session.execute(stmt)).rowcount)  # type: ignore[attr-defined]
