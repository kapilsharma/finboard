"""Every table with a `user_id` column must have RLS enabled, forced, and an owner policy."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from finboard.db.models import USER_OWNED_TABLES


async def test_every_user_owned_table_is_protected(owner_engine: AsyncEngine) -> None:
    async with owner_engine.connect() as conn:
        rows = (
            await conn.execute(
                text("""
            SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                   EXISTS (SELECT 1 FROM pg_policies p
                           WHERE p.tablename = c.relname AND p.policyname = c.relname || '_is_owner')
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public'
            WHERE c.relkind = 'r'
              AND EXISTS (SELECT 1 FROM information_schema.columns col
                          WHERE col.table_schema = 'public' AND col.table_name = c.relname
                            AND col.column_name = 'user_id')
            ORDER BY c.relname
        """)
            )
        ).all()

    assert {r[0] for r in rows} == set(USER_OWNED_TABLES)
    unprotected = [r[0] for r in rows if not (r[1] and r[2] and r[3])]
    assert unprotected == []
