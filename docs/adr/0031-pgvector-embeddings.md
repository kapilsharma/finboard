# ADR-0031: pgvector for embeddings, inside the existing Postgres

**Status:** Accepted (owner decision 2026-11-04). Amends [ADR-0022](0022-postgresql.md) (image and extension list).

**Context.** Category suggestions ([ADR-0030](0030-assistive-ai-opt-in.md)) need nearest-neighbour search over embeddings of transaction descriptions. The options were ChromaDB, FAISS, Qdrant (another container) and pgvector.

**Decision.** Use **pgvector** in the existing PostgreSQL 18.
- The Compose and CI database image becomes `pgvector/pgvector:pg18` (Postgres 18 needs pgvector 0.8.1 or later). A migration run as `finboard_owner` executes `CREATE EXTENSION IF NOT EXISTS vector`.
- A new user-owned table, `txn_embedding`, has `user_id`, a composite FK to `txn` with `ON DELETE CASCADE`, `model`, and `embedding vector(384)`. It has **RLS like every other user-owned table** ([ADR-0025](0025-tenant-isolation-rls.md)).
- Access goes through our repositories with the `pgvector` Python package (SQLAlchemy + asyncpg). **LangChain's `PGVector` store is not used**, because it creates and manages its own tables outside our migrations, repositories and RLS conventions. LangChain and LangGraph are used for the LLM workflow, not for storage.
- **No ANN index at first.** An exact cosine scan of one user's rows (≤ 50k) is fast with the `user_id` index. Add HNSW (`vector_cosine_ops`) only if the perf test misses its budget. If we do, note that HNSW filters *after* the index search, so a `user_id` filter can return fewer than k neighbours. pgvector 0.8's iterative index scans (`hnsw.iterative_scan = relaxed_order`) address this, and the suggestion eval must be re-run with the index on.

**Options considered.**

| Option | Strength | Why not |
|---|---|---|
| ChromaDB (embedded or server) | Popular in RAG tutorials; simple API | No per-user isolation: tenancy would be an app-side filter only, so one missing `where` leaks across users. A second store to back up and keep consistent with deletes |
| FAISS (in-process index) | Very fast; no service | No persistence or filtering model of its own; we'd build storage, per-user partitioning, deletion and backups ourselves. Index lives per process, which doesn't fit stateless API instances |
| Qdrant (container) | Strong vector DB with payload filters | Another service on a 16 GB laptop; isolation again by filter, not enforced by the database; separate backups |
| LangChain `PGVector` store | Quick to wire up | Creates and manages its own tables outside our migrations, repositories and RLS policies; the `user_id`, composite FKs and cascade deletes would be ours to bolt on, and easy to get wrong |
| **pgvector in our Postgres, our own table** | Same database, same RLS, same migrations, same backups | **Chosen** |

**Why.** One database: no extra service on a 16 GB laptop and no second backup. Tenant isolation comes for free through RLS, which Chroma and FAISS don't have. Similarity search, filters (account, direction, date) and joins to categories happen in one SQL query. Embeddings are deleted with their transaction in the same transaction. `pg_dump` and per-user exports already cover the new table.

**Consequences.** We use a community image instead of the official `postgres:18` (it is the official image plus the extension). A hosted deployment needs a managed Postgres that offers pgvector (most do). Embeddings depend on the model, so `model` is stored and a model change triggers a re-embed job.
