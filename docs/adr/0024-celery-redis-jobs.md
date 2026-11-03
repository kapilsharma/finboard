# ADR-0024: Background jobs with Celery 5 + Redis

**Status:** Accepted (owner chose "Redis + arq/Celery" on 2026-10-18; this ADR picks Celery). Supersedes [ADR-0010](0010-parse-in-child-process.md).

**Decision.** Celery 5 with a Redis 7 broker. Queues `parse` (CPU-bound, prefork) and `default`, plus a beat scheduler for maintenance. JSON serializer only. **No result backend**: job state lives in the Postgres `job` table, which the API exposes as `/jobs/{id}`. Tasks receive ids only, never bytes or secrets. `acks_late`, idempotent tasks, retries for transient infrastructure errors only. `parse` uses `soft_time_limit=60`, `time_limit=75`, `max_tasks_per_child=50`.

**Why Celery over arq.** PDF parsing is synchronous and CPU-bound, which suits Celery's prefork pool. Its hard time limit kills a hung parse. It is the most widely used and documented Python task queue. arq is async-native, but it runs everything on one event loop, which is a poor fit for CPU work, and it is in maintenance mode.

**Trade-offs.** Celery tasks are sync. Calling the async services goes through a small per-worker-process event-loop bridge. Celery prefork isn't supported on Windows hosts, so Windows developers run the worker with `--pool=solo` (no hard kill) or in Docker. The v1 user setup runs everything in Docker.
