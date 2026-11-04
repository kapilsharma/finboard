"""ORM models. Every user-owned table has `user_id`, a `(user_id, id)` unique key as the target
for composite foreign keys, and a row-level-security policy created in its migration."""

import datetime as dt
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
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
from finboard.domain.enums import (
    AccountType,
    CategorisedBy,
    CategoryType,
    Direction,
    ImportRowOutcome,
    ImportSource,
    ImportStatus,
    JobStatus,
    ReconStatus,
)

Money = Numeric(14, 2, asdecimal=True)


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

    __table_args__ = (UniqueConstraint("user_id", "id"),)


Index("ix_job_user_created", Job.user_id, Job.created_at.desc())


def _user_fk(column: str, target: str, *, ondelete: str | None = None) -> ForeignKeyConstraint:
    """Composite FK `(user_id, column) -> target(user_id, id)`: a row can only point at the same
    user's data (ADR-0025). For a nullable column, `SET NULL (column)` keeps user_id intact."""
    return ForeignKeyConstraint(
        ["user_id", column],
        [f"{target}.user_id", f"{target}.id"],
        ondelete=ondelete,
    )


class ImportBatch(UUIDPrimaryKey, UserOwned, Timestamps, Base):
    """One uploaded statement file and its journey: parse, preview, commit (ARCHITECTURE §7)."""

    __tablename__ = "import_batch"

    account_id: Mapped[uuid.UUID | None]
    job_id: Mapped[uuid.UUID | None]  # the latest parse job
    status: Mapped[ImportStatus] = mapped_column(str_enum(ImportStatus, "import_status"))
    source: Mapped[ImportSource] = mapped_column(
        str_enum(ImportSource, "import_source"), server_default=text("'upload'")
    )
    file_name: Mapped[str] = mapped_column(String(255))
    file_sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(BigInteger)
    blob_key: Mapped[str | None] = mapped_column(String(200))
    encrypted: Mapped[bool] = mapped_column(server_default=text("false"))
    archived: Mapped[bool] = mapped_column(server_default=text("false"))
    # Overrides from re-parse; detection and matching decide when unset.
    requested_parser_id: Mapped[str | None] = mapped_column(String(64))
    parser_id: Mapped[str | None] = mapped_column(String(64))
    parser_version: Mapped[str | None] = mapped_column(String(32))
    parser_confidence: Mapped[float | None] = mapped_column(Float)
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    account_suggestion: Mapped[dict[str, Any] | None]
    institution: Mapped[str | None] = mapped_column(String(120))
    account_hint: Mapped[str | None] = mapped_column(String(4))
    balance_kind: Mapped[str | None] = mapped_column(String(10))
    period_start: Mapped[dt.date | None]
    period_end: Mapped[dt.date | None]
    opening_balance: Mapped[Decimal | None] = mapped_column(Money)
    closing_balance: Mapped[Decimal | None] = mapped_column(Money)
    recon_status: Mapped[ReconStatus | None] = mapped_column(str_enum(ReconStatus, "recon_status"))
    recon_credits: Mapped[Decimal | None] = mapped_column(Money)
    recon_debits: Mapped[Decimal | None] = mapped_column(Money)
    recon_expected_closing: Mapped[Decimal | None] = mapped_column(Money)
    recon_diff: Mapped[Decimal | None] = mapped_column(Money)
    recon_first_break_seq: Mapped[int | None]
    recon_overridden: Mapped[bool] = mapped_column(server_default=text("false"))
    rows_parsed: Mapped[int] = mapped_column(server_default=text("0"))
    rows_inserted: Mapped[int] = mapped_column(server_default=text("0"))
    rows_skipped: Mapped[int] = mapped_column(server_default=text("0"))
    rows_excluded: Mapped[int] = mapped_column(server_default=text("0"))
    warnings: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    error: Mapped[str | None] = mapped_column(Text)
    committed_at: Mapped[datetime | None]
    rolled_back_at: Mapped[datetime | None]
    expires_at: Mapped[datetime | None]

    __table_args__ = (
        UniqueConstraint("user_id", "id"),
        _user_fk("account_id", "account", ondelete="SET NULL (account_id)"),
        _user_fk("job_id", "job", ondelete="SET NULL (job_id)"),
        CheckConstraint("file_size >= 0", name="file_size_not_negative"),
    )


Index(
    "ix_import_batch_user_status_created",
    ImportBatch.user_id,
    ImportBatch.status,
    ImportBatch.created_at.desc(),
)
Index("ix_import_batch_user_sha256", ImportBatch.user_id, ImportBatch.file_sha256)


class StagedRow(UserOwned, Base):
    """A parsed row waiting in the preview (ADR-0011). As sensitive as a transaction."""

    __tablename__ = "staged_row"

    import_id: Mapped[uuid.UUID]
    seq: Mapped[int] = mapped_column(Integer)
    date: Mapped[dt.date]
    value_date: Mapped[dt.date | None]
    description_raw: Mapped[str] = mapped_column(Text)
    description_norm: Mapped[str] = mapped_column(Text)
    amount: Mapped[Decimal] = mapped_column(Money)
    direction: Mapped[Direction] = mapped_column(str_enum(Direction, "direction"))
    balance_after: Mapped[Decimal | None] = mapped_column(Money)
    raw: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    duplicate_of: Mapped[uuid.UUID | None]
    possible_duplicate: Mapped[bool] = mapped_column(server_default=text("false"))
    include: Mapped[bool] = mapped_column(server_default=text("true"))
    category_id: Mapped[uuid.UUID | None]
    rule_id: Mapped[uuid.UUID | None]  # FK arrives with the rule table (M3)
    categorised_by: Mapped[CategorisedBy | None] = mapped_column(
        str_enum(CategorisedBy, "categorised_by")
    )

    __table_args__ = (
        PrimaryKeyConstraint("import_id", "seq"),
        _user_fk("import_id", "import_batch", ondelete="CASCADE"),
        _user_fk("duplicate_of", "txn", ondelete="SET NULL (duplicate_of)"),
        _user_fk("category_id", "category", ondelete="SET NULL (category_id)"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )


class Txn(UUIDPrimaryKey, UserOwned, Timestamps, Base):
    """A committed transaction. Amounts are positive; `direction` carries the sign (ADR-0008)."""

    __tablename__ = "txn"

    account_id: Mapped[uuid.UUID]
    import_id: Mapped[uuid.UUID | None]
    date: Mapped[dt.date]
    value_date: Mapped[dt.date | None]
    description_raw: Mapped[str] = mapped_column(Text)
    description_norm: Mapped[str] = mapped_column(Text)
    payee_label: Mapped[str | None] = mapped_column(String(120))
    amount: Mapped[Decimal] = mapped_column(Money)
    direction: Mapped[Direction] = mapped_column(str_enum(Direction, "direction"))
    balance_after: Mapped[Decimal | None] = mapped_column(Money)
    category_id: Mapped[uuid.UUID]
    type: Mapped[CategoryType] = mapped_column(str_enum(CategoryType, "category_type"))
    categorised_by: Mapped[CategorisedBy] = mapped_column(str_enum(CategorisedBy, "categorised_by"))
    rule_id: Mapped[uuid.UUID | None]
    needs_review: Mapped[bool] = mapped_column(server_default=text("false"))
    fingerprint: Mapped[str] = mapped_column(String(64))
    fingerprint_version: Mapped[int] = mapped_column(SmallInteger)
    notes: Mapped[str | None] = mapped_column(Text)
    raw: Mapped[dict[str, Any]] = mapped_column(server_default=text("'{}'::jsonb"))

    __table_args__ = (
        UniqueConstraint("user_id", "id"),
        UniqueConstraint("user_id", "fingerprint"),
        _user_fk("account_id", "account"),
        _user_fk("import_id", "import_batch", ondelete="SET NULL (import_id)"),
        _user_fk("category_id", "category"),
        CheckConstraint("amount > 0", name="amount_positive"),
    )


Index("ix_txn_user_date_id", Txn.user_id, Txn.date.desc(), Txn.id)
Index("ix_txn_user_account_date", Txn.user_id, Txn.account_id, Txn.date)
Index("ix_txn_user_category_date", Txn.user_id, Txn.category_id, Txn.date)
Index("ix_txn_user_date_needs_review", Txn.user_id, Txn.date, postgresql_where=text("needs_review"))
Index(
    "ix_txn_description_norm_trgm",
    Txn.description_norm,
    postgresql_using="gin",
    postgresql_ops={"description_norm": "gin_trgm_ops"},
)


class ImportRow(UserOwned, Base):
    """Every fingerprint an import saw and what happened to it (ADR-0016). A rollback hands rows
    that another committed import also saw over to that import instead of deleting them."""

    __tablename__ = "import_row"

    import_id: Mapped[uuid.UUID]
    fingerprint: Mapped[str] = mapped_column(String(64))
    txn_id: Mapped[uuid.UUID]
    outcome: Mapped[ImportRowOutcome] = mapped_column(
        str_enum(ImportRowOutcome, "import_row_outcome")
    )

    __table_args__ = (
        PrimaryKeyConstraint("import_id", "fingerprint"),
        _user_fk("import_id", "import_batch", ondelete="CASCADE"),
        _user_fk("txn_id", "txn", ondelete="CASCADE"),
    )


Index("ix_import_row_txn", ImportRow.txn_id)
Index("ix_import_row_user_fingerprint", ImportRow.user_id, ImportRow.fingerprint)


class UserSetting(Base):
    __tablename__ = "user_setting"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("app_user.id", ondelete="CASCADE"), primary_key=True
    )
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Any] = mapped_column(JSONB)


# Tables protected by row-level security. A test asserts this matches every table that has a
# `user_id` column, so a new table can't be added without a policy.
USER_OWNED_TABLES = (
    "account",
    "category",
    "job",
    "user_setting",
    "import_batch",
    "staged_row",
    "txn",
    "import_row",
)
