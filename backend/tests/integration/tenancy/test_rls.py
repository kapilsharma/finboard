"""Postgres itself enforces isolation, even if application code forgets a filter (ADR-0025).

These tests use raw SQL as the runtime role `finboard_app`, bypassing repositories entirely.
"""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from finboard.auth import Principal


async def _as(conn: AsyncConnection, user: Principal | None) -> None:
    if user is not None:
        await conn.execute(
            text("SELECT set_config('app.user_id', :u, true)"), {"u": str(user.user_id)}
        )


async def _count(engine: AsyncEngine, user: Principal | None, table: str) -> int:
    async with engine.begin() as conn:
        await _as(conn, user)
        return int((await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one())


async def test_runtime_role_cannot_bypass_rls(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT current_user, rolbypassrls, rolsuper FROM pg_roles WHERE rolname = current_user"
                )
            )
        ).one()
    assert tuple(row) == ("finboard_app", False, False)


async def test_each_user_sees_only_own_rows(
    app_engine: AsyncEngine, alice: Principal, bob: Principal
) -> None:
    alice_categories = await _count(app_engine, alice, "category")
    assert alice_categories > 0
    assert await _count(app_engine, bob, "category") == alice_categories  # own defaults only
    async with app_engine.begin() as conn:
        await _as(conn, alice)
        names = (await conn.execute(text("SELECT DISTINCT user_id FROM category"))).scalars().all()
    assert names == [alice.user_id]


async def test_no_identity_sees_nothing(app_engine: AsyncEngine, alice: Principal) -> None:
    assert await _count(app_engine, None, "category") == 0


async def test_cannot_write_rows_for_another_user(
    app_engine: AsyncEngine, alice: Principal, bob: Principal
) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with app_engine.begin() as conn:
            await _as(conn, bob)
            await conn.execute(
                text("INSERT INTO account (user_id, name, type) VALUES (:u, 'stolen', 'savings')"),
                {"u": str(alice.user_id)},
            )


async def test_cannot_update_another_users_rows(
    app_engine: AsyncEngine, alice: Principal, bob: Principal
) -> None:
    async with app_engine.begin() as conn:
        await _as(conn, bob)
        result = await conn.execute(
            text("UPDATE category SET name = 'pwned' WHERE user_id = :u"), {"u": str(alice.user_id)}
        )
    assert result.rowcount == 0


async def test_composite_fk_blocks_cross_user_parent(
    app_engine: AsyncEngine, owner_engine: AsyncEngine, alice: Principal, bob: Principal
) -> None:
    async with app_engine.begin() as conn:
        await _as(conn, alice)
        alice_category: uuid.UUID = (
            await conn.execute(text("SELECT id FROM category LIMIT 1"))
        ).scalar_one()

    with pytest.raises(DBAPIError, match="fk_category_parent"):
        async with app_engine.begin() as conn:
            await _as(conn, bob)
            await conn.execute(
                text(
                    "INSERT INTO category (user_id, name, type, parent_id) VALUES (:u, 'x', 'expense', :p)"
                ),
                {"u": str(bob.user_id), "p": str(alice_category)},
            )
