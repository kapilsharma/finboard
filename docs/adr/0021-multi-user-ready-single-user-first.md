# ADR-0021: Multi-user-ready architecture, single user shipped first

**Status:** Accepted (owner decision 2026-10-18). Changes HANDOVER §3 "single user, no login" from an *architectural* assumption to a *v1 scope* limit.

**Context.** The owner is the only v1 user, but a goal of the project is learning how FastAPI is structured for a large system with hundreds of users.

**Decision.**
- Every user-owned row carries `user_id`. Isolation is enforced in three layers: repositories, composite FKs and Postgres RLS ([ADR-0025](0025-tenant-isolation-rls.md)).
- Authentication sits behind one FastAPI dependency, `get_principal() -> Principal`, backed by an `AuthBackend` protocol. **v1 ships `LocalSingleUserBackend`** (a fixed `local` user). A session/OIDC backend can be added later without touching routes or services.
- API and workers are stateless and scale horizontally. Slow work goes through a job queue ([ADR-0024](0024-celery-redis-jobs.md)).
- `FINBOARD_MODE=local|server`. v1 supports and documents `local` only. `server` refuses to start until a real auth backend exists.

**Consequences.** More moving parts than a local SQLite app: Postgres, Redis and a worker, all run via Docker Compose. In exchange there is a realistic structure to learn from, and no redesign when hosting becomes real. The v1 scope stays as HANDOVER §8: no login UI, no cloud.
