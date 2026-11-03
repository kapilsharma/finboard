"""Row-level-security helpers for migrations (ADR-0025)."""

from alembic import op

# NULLIF: once a transaction-local setting ends, Postgres leaves '' behind, not NULL.
CURRENT_USER_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def enable_user_rls(table: str) -> None:
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    # FORCE: the policy applies to the table owner as well, not just other roles.
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY {table}_is_owner ON {table} "
        f"USING (user_id = {CURRENT_USER_EXPR}) "
        f"WITH CHECK (user_id = {CURRENT_USER_EXPR})"
    )


def disable_user_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS {table}_is_owner ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
