"""user password: an argon2id hash on app_user for server-mode sign-in (M8, ADR-0041).

NULL means the user can't sign in with a password: the `local` user of local mode, or an
account whose password the operator hasn't set yet. app_user has no row-level security (it
holds no financial data), which is what lets sign-in look a user up before anyone is known.

Revision ID: a41c7e0d93b2
Revises: 6486259d7a16
Create Date: 2026-11-16 12:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a41c7e0d93b2"
down_revision: str | None = "6486259d7a16"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "password_hash")
