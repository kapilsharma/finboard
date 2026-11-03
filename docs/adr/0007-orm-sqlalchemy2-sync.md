# ADR-0007: SQLAlchemy 2 (sync) + Alembic, not SQLModel

**Status:** Superseded by [ADR-0023](0023-async-sqlalchemy.md) (owner decision 2026-10-18: async throughout).

**Still valid from this ADR.** SQLAlchemy 2 rather than SQLModel: DB models and API schemas are separate classes, because their shapes differ, and SQLModel lags SQLAlchemy releases. Alembic from the first commit.
