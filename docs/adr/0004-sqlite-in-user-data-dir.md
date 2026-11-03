# ADR-0004: SQLite single file in a user data dir

**Status:** Superseded by [ADR-0022](0022-postgresql.md) (owner decision 2026-10-18). Originally Accepted (given — HANDOVER §2, §3).

**Original decision.** One SQLite file in an OS data dir. Zero-ops and easy backup.

**Why superseded.** The owner wants the system designed for hundreds of concurrent users, partly to learn how a large FastAPI system is built. SQLite's single writer and lack of row-level security don't fit that.
