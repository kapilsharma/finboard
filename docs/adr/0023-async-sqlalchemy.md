# ADR-0023: Async throughout — SQLAlchemy 2 asyncio + asyncpg, Unit of Work, repositories

**Status:** Accepted (owner decision 2026-10-18). Supersedes [ADR-0007](0007-orm-sqlalchemy2-sync.md).

**Decision.**
- FastAPI `async def` routes. SQLAlchemy 2 `AsyncEngine`/`AsyncSession` on asyncpg. Alembic 1.x with the async `env.py` template.
- **Repositories** own all SQL. A **UnitOfWork** (one `AsyncSession`, one transaction) is provided per request by `get_uow()`, which also runs `SET LOCAL app.user_id` for RLS.
- `expire_on_commit=False`. Relationships default to `lazy="raise"`, so async code can't trigger hidden I/O and loading is always explicit (`selectinload`).
- Sync code exists in exactly two places, both outside the event loop: parser adapters (CPU-bound, run in Celery workers) and Celery task entry points, which bridge to async services through a per-process event loop (`jobs/runtime.py`).
- Separate Pydantic API schemas (unchanged from ADR-0007).

**Consequences.** Async needs discipline: no blocking calls in routes (ruff `ASYNC` rules enabled), explicit eager loading, careful test fixtures (pytest-asyncio, savepoint-per-test).
