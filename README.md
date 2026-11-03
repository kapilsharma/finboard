# Finboard

A private personal-finance app. Import your bank statements (password-protected PDFs), let
**rules you control** categorise every transaction (no AI), and see where your money goes:
income, spending, savings rate, budgets and per-account totals.

Your data stays on your machine. The code is open source (MIT); your statements never are.

> **Status:** early development. Milestone **M1 (platform skeleton)** is done: accounts,
> categories, preferences, background worker. Statement import arrives in M2. See
> [docs/ROADMAP.md](docs/ROADMAP.md).

## Architecture in one picture

React SPA → FastAPI (async, stateless) → PostgreSQL (row-level security per user), with slow work
(PDF parsing) on Celery workers via Redis. Built for one user on one machine today, structured for
many users later. Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the decision records in
[docs/adr/](docs/adr/README.md).

## Development

Prerequisites: Docker, [uv](https://docs.astral.sh/uv/), Node 22+.

```sh
docker compose -f deploy/compose.dev.yaml up -d   # Postgres 18 + Redis 7 on 127.0.0.1 only
cd frontend && npm install && cd ..
cd backend && uv sync
uv run finboard dev                               # API (reload) + worker + Vite
```

Open http://127.0.0.1:5173. API docs: http://127.0.0.1:8765/api/docs.

| Task | Command (from `backend/` or `frontend/`) |
|---|---|
| Backend tests (needs the compose stack) | `uv run pytest` |
| Backend lint / types / layers | `uv run ruff check src tests` · `uv run mypy` · `uv run lint-imports` |
| Frontend tests / lint / types | `npm test` · `npm run lint` · `npm run typecheck` |
| Regenerate API types after changing the API | `npm run gen:api` |
| New migration | `uv run alembic revision --autogenerate -m "…"` (then add RLS for new user tables) |
| Single-port production mode | `npm run build` then `uv run finboard serve` → http://127.0.0.1:8765 |

## Privacy rules for contributors

- Never commit statements, databases, dumps or exports. A pre-commit hook and CI enforce this
  (`scripts/check_no_private_data.py`). Install hooks with `uvx pre-commit install`.
- Test fixtures are generated synthetic PDFs. Never attach a real statement to an issue.
- Nothing calls out to the internet: no telemetry, no CDNs, no update checks.

## Licence

[MIT](LICENSE)
