# ADR-0034: Per-user parse cap, and recording hard-killed parses

**Status:** Accepted (2026-11-04, M2 / issue #2). Refines [ADR-0010](0010-parse-in-child-process.md), [ADR-0024](0024-celery-redis-jobs.md) and ARCHITECTURE §6–§7.

**Context.** Parsing runs in Celery's `parse` queue with a soft and a hard time limit (`FINBOARD_PARSE_SOFT_TIME_LIMIT`, default 60 s; `FINBOARD_PARSE_TIME_LIMIT`, default 75 s). Two gaps showed up while building M2:
1. **Fairness.** A user who drops 30 statements at once would fill the parse queue, and other users' uploads would wait behind all of them. Celery has no per-tenant concurrency control, and a rate limit on the task is global.
2. **Hard kills are silent.** When the hard limit fires, the pool kills the child process. The task's own `try/except/finally` never runs, and with no result backend Celery records nothing. The import and its job would stay `processing` forever, and the user's parse slot would never be freed.

**Decision.**
1. **Parse cap per user** (`FINBOARD_PARSE_CONCURRENCY_PER_USER`, default 2). On upload, the service takes a transaction-scoped advisory lock for the user (`pg_advisory_xact_lock(hashtextextended('finboard:parse:' || user_id, 0))`) and counts the user's in-flight imports (`queued` or `processing`).
   - Below the cap: enqueue `imports.process` and set the import to `queued`.
   - At the cap: commit the import as `uploaded` (file stored, no job yet). The API answers 202 either way.
2. **Waiting imports are started by whoever frees a slot.** At the end of every parse, success or failure, the worker calls `ImportService.start_waiting()`. Under the same lock, it submits the oldest `uploaded` imports until the user is back at the cap. A failure in this step is logged and never changes the finished import's outcome. No beat task or polling is needed.
3. **Hard kills are recorded in the parent process.** `imports.process` uses a custom task class whose `Request.on_timeout` runs in the worker's parent process when a limit fires. For the hard limit it calls `mark_killed()`, which:
   - sets the job to `failed` and the import to `failed`, each with a fixed, user-safe message;
   - frees the slot by calling `start_waiting()`.

   It only acts on ids taken from the task's keyword arguments, which are ids only (CLAUDE.md, ADR-0027).
4. **The soft limit stays the normal path.** `SoftTimeLimitExceeded` is raised inside the parse. The service catches it and fails the import as for any other parse error. The parser registry re-raises it from `detect()` rather than scoring that parser 0, which used to turn a timeout into "No parser recognised this file".

**Consequences.**
- `uploaded` is a real, visible state (shown as "Waiting") on the Import page and in the import history.
- The hard-kill path needs the prefork pool, so it only works on Linux and in Docker. On Windows the dev worker uses `--pool=solo`, where hard limits don't apply (CLAUDE.md, Gotchas). `tests/integration/test_parse_timeout.py` starts a real prefork worker with a sleeping adapter, and skips on Windows.
- The per-user lock serialises only "is there a free slot?" decisions, never the parse itself.

**Alternatives rejected.**
- A dedicated queue per user, or Celery routing by user: doesn't scale to many users and needs worker reconfiguration.
- A Redis semaphore: it can leak when a worker dies, and it's a second source of truth next to the import's status in Postgres.
- A beat task that sweeps stuck `processing` imports: it adds latency and guesswork about what "stuck" means, while `on_timeout` knows exactly which task died. A sweep may still come later as a backstop for worker crashes (OOM, host restart), with M7's beat service.
