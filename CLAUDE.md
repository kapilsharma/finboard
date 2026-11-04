# CLAUDE.md

Guidance for AI coding sessions (and a quick reference for humans). Read this first, then the
docs listed below. Keep this file short; details belong in `docs/`.

## What Finboard is
A private personal-finance app: import password-protected PDF bank statements through
bank-specific **parser adapters**, categorise transactions with **user-editable rules**, show a
dashboard. Optional, off-by-default AI features. Built for one user on one machine, structured
for many users (async FastAPI, Postgres with row-level security, Celery workers).

## Sources of truth (read before changing anything)
- `docs/ARCHITECTURE.md`: design. Section numbers are referenced from issues.
- `docs/adr/`: decisions and *why*. Don't silently deviate: write a new ADR (or amend one,
  with status and date) for any significant decision or deviation.
- `docs/ROADMAP.md`: each milestone's **acceptance table is the definition of done**.
  Mark the milestone done and note deviations when you finish it.
- `docs/OPEN_QUESTIONS.md`: owner decisions and defaults.
- `docs/handover/`: original requirements and the approved dashboard mockup.

## Environment
- Python 3.12+ with `uv`; Node 22+ with npm; Postgres 18 + Redis 7.
- Services, with Docker: `docker compose -f deploy/compose.dev.yaml up -d`.
  Without Docker (Debian/Ubuntu, e.g. cloud sandboxes): `bash scripts/setup-native-services.sh`.
  Both give Postgres on `127.0.0.1:55432` and Redis on `127.0.0.1:56379`. The defaults in
  `backend/src/finboard/core/config.py` and `backend/tests/conftest.py` match; no `.env` needed.
- Install: `cd backend && uv sync` and `cd frontend && npm ci`.
- Run: `cd backend && uv run finboard dev` (API :8765, worker, Vite :5173).

## Definition of done
```
bash scripts/ci-local.sh          # same checks as GitHub Actions; must pass
bash scripts/ci-local.sh --fast   # quicker loop while working (no installs, no build)
```
On Windows: `powershell -File scripts\ci-local.ps1`. CI on the PR must also be green.
If you add a CI step, add it to `scripts/ci-local.sh` too (and vice versa).

## Working an issue
1. Branch `issue-<n>-<short-slug>` from `main`.
2. Read the issue's "Read first" list. The ROADMAP acceptance rows need a test each.
3. Commit in logical steps. Open one PR with `Closes #<n>`, a summary, and a list of
   decisions or deviations (and the ADRs written for them).
4. Update `docs/ROADMAP.md` (status), and ARCHITECTURE/ADRs where reality differs.

## Backend conventions
- Layers (enforced by `uv run lint-imports`):
  `cli → main → api → jobs → services → auth → db → domain`. `domain` is pure (no I/O).
- **Services own the transaction**: they call `await uow.commit()` explicitly. Routes stay
  thin; repositories hold all SQL.
- **Every user-owned table**:
  - a `user_id` FK to `app_user` ON DELETE CASCADE, and `UNIQUE (user_id, id)`;
  - **composite FKs** to other user tables (`(user_id, x_id) → x(user_id, id)`);
  - `enable_user_rls("<table>")` in the migration;
  - the table name added to `USER_OWNED_TABLES` in `db/models.py`.

  The RLS coverage test fails if you forget.
- Migrations: `uv run alembic revision --autogenerate -m "..."`, then review the file and add
  RLS by hand. `alembic check` runs in the tests.
- Columns the DB sets on UPDATE need `eager_defaults` (the `Timestamps` mixin has it);
  otherwise async code fails with `MissingGreenlet`. Relationships: load explicitly.
- Money: `NUMERIC(14,2)` / `Decimal` / decimal **strings** in JSON. Never floats.
- Errors: raise `finboard.domain.errors.*`; `api/errors.py` turns them into problem+json with a
  stable `code`. No `HTTPException` below `api`.
- Background work: Celery tasks in `jobs/tasks.py` stay thin (ids in, call a service).
  Arguments are ids only, never data or secrets. Tests use `RecordingJobQueue` and call the
  task body directly.
- Mutating requests need the header `X-Finboard-Client: 1` (CSRF guard, ADR-0015).

## Frontend conventions
- Server state in TanStack Query (`src/api/hooks.ts`); UI state (month, filters) in the URL.
- API types are generated: after any API change run `npm run gen:api` in `frontend/` and
  commit `src/api/schema.d.ts` (CI fails if it is stale).
- CSS Modules + tokens in `src/theme/tokens.css`; must work in light and dark, and at 400 px.
- No money arithmetic in the browser; format with `src/lib/format.ts` (en-IN, ₹, lakh).

## Tests
- Backend: `tests/unit` (pure, all OSes), `tests/integration` (Postgres + Redis; the
  database must be named `*_test`; tables are truncated after each test),
  `tests/integration/tenancy` (user B must never see user A's data).
- Frontend: Vitest + Testing Library; `mockApi()` in `src/test/utils.tsx` stubs fetch.
- Prefer tests that would have caught a real bug over tests of implementation details.

## Privacy rules (non-negotiable)
- **Never commit** statements, PDFs, databases, dumps, exports or `.env`. Fixtures are
  generated at test time (reportlab) into `tmp_path`. `scripts/check_no_private_data.py`
  enforces this in pre-commit and CI.
- Never log descriptions, amounts, file names or passwords (the logger redacts known keys;
  don't rely on it).
- No outbound network calls, except the opt-in AI path through `finboard.ai.llm`
  (ADR-0030). Read ADR-0030 and ADR-0032 before touching anything AI-related.

## Gotchas
- `uv` might not be on PATH on the owner's Windows machine. Scripts expect it on PATH.
- Celery's prefork pool doesn't run on Windows hosts; the dev worker uses `--pool=solo` there,
  so hard time limits only apply on Linux and in Docker.
- In Git Bash, prefer writing files with your editor tools over heredocs containing
  apostrophes (they have broken shell quoting before).
