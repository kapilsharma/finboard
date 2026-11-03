"""ORM models. Every user-owned table has `user_id`, a `(user_id, id)` unique key as the target
for composite foreign keys, and a row-level-security policy created in its migration."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from finboard.db.base import Base, Timestamps, UserOwned, UUIDPrimaryKey, str_enum
from finboard.domain.enums import AccountType, CategoryType, JobStatus


class AppUser(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "app_user"

    username: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str | None] = mapped_column(CITEXT, unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    # Bumped on every write to the user's financial data; used for HTTP caching (ETag).
    data_version: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))


class Account(UUIDPrimaryKey, UserOwned, Timestamps, Base):
    __tablename__ = "account"

    name: Mapped[str] = mapped_column(String(80))
    institution: Mapped[str | None] = mapped_column(String(80))
    type: Mapped[AccountType] = mapped_column(str_enum(AccountType, "account_type"))
    masked_number: Mapped[str | None] = mapped_column(String(4))
    parser_id: Mapped[str | None] = mapped_column(String(64))
    currency: Mapped[str] = mapped_column(String(3), server_default=text("'INR'"))
    active: Mapped[bool] = mapped_column(server_default=text("true"))
    colour: Mapped[str | None] = mapped_column(String(7))

    __table_args__ = (
        UniqueConstraint("user_id", "id"),
        CheckConstraint("masked_number ~ '^[0-9]{1,4}$'", name="masked_number_digits"),
        CheckConstraint("currency = 'INR'", name="currency_inr"),
    )


Index("uq_account_user_name", Account.user_id, func.lower(Account.name), unique=True)


class Category(UUIDPrimaryKey, UserOwned, Timestamps, Base):
    __tablename__ = "category"

    name: Mapped[str] = mapped_column(String(60))
    parent_id: Mapped[uuid.UUID | None]
    type: Mapped[CategoryType] = mapped_column(str_enum(CategoryType, "category_type"))
    colour: Mapped[str | None] = mapped_column(String(7))
    # System categories (Uncategorized, Card payment, …) can be renamed but not deleted.
    is_system: Mapped[bool] = mapped_column(server_default=text("false"))
    system_key: Mapped[str | None] = mapped_column(String(40))
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))
    archived: Mapped[bool] = mapped_column(server_default=text("false"))

    __table_args__ = (
        UniqueConstraint("user_id", "id"),
        # Composite FK: a parent can only be one of the same user's categories.
        ForeignKeyConstraint(
            ["user_id", "parent_id"],
            ["category.user_id", "category.id"],
            name="fk_category_parent",
        ),
    )


Index(
    "uq_category_user_parent_name",
    Category.user_id,
    Category.parent_id,
    func.lower(Category.name),
    unique=True,
    postgresql_nulls_not_distinct=True,
)
Index(
    "uq_category_user_system_key",
    Category.user_id,
    Category.system_key,
    unique=True,
    postgresql_where=Category.system_key.is_not(None),
)


class Job(UUIDPrimaryKey, UserOwned, Base):
    """A unit of background work. The Celery task id equals the job id (ADR-0024)."""

    __tablename__ = "job"

    kind: Mapped[str] = mapped_column(String(64))
    status: Mapped[JobStatus] = mapped_column(str_enum(JobStatus, "job_status"))
    progress: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    params: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    result: Mapped[dict[str, Any] | None]
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    started_at: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]


Index("ix_job_user_created", Job.user_id, Job.created_at.desc())


class UserSetting(Base):
    __tablename__ = "user_setting"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)


# Tables protected by row-level security. A test asserts this matches every table that has a
# `user_id` column, so a new table can't be added without a policy.
USER_OWNED_TABLES = ("account", "category", "job", "user_setting")
