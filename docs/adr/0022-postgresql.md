# ADR-0022: PostgreSQL 18 as the only database

**Status:** Accepted (owner decision 2026-10-18). Supersedes [ADR-0004](0004-sqlite-in-user-data-dir.md).

**Decision.** PostgreSQL 18 (official `postgres:18` image in Compose; any managed PG 18 when hosted). Driver: asyncpg. Extensions: `pg_trgm` (description search), `citext` (emails). Two roles: `finboard_owner` (migrations, owns tables) and `finboard_app` (runtime, `NOBYPASSRLS`).

**Why Postgres only.** Real concurrent writers, RLS for tenant isolation, exact NUMERIC, `uuidv7()`, partial and trigram indexes, `FOR UPDATE`/`SKIP LOCKED`, and `INSERT … ON CONFLICT`. Supporting SQLite as well would double the test matrix and limit us to the common subset.

**Consequences.** Local runs need Docker, which replaces the "single SQLite file" experience. Per-user backup becomes a logical export (JSON + blobs zip). Whole-system backup is `pg_dump`.
