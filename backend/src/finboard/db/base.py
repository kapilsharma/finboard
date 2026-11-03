import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, MetaData, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 (read by SQLAlchemy at class creation)
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


def str_enum(enum_cls: type[StrEnum], name: str) -> Enum:
    """TEXT column + CHECK constraint (easier to migrate than native PG enums)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class UUIDPrimaryKey:
    # UUIDv7: time-ordered, not enumerable across tenants (ADR-0028).
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, server_default=text("uuidv7()"))


class Timestamps:
    # Fetch server-generated values (updated_at) with RETURNING on INSERT/UPDATE. Without this
    # they are expired after flush, and reading them would need lazy I/O — not allowed in async.
    __mapper_args__ = {"eager_defaults": True}  # noqa: RUF012

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class UserOwned:
    """The row belongs to one user. Repositories and Postgres RLS both key on this (ADR-0025)."""

    @declared_attr
    def user_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"))
