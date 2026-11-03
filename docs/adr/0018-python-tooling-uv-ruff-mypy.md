# ADR-0018: Tooling

**Status:** Accepted (revised 2026-10-18 for async/Postgres)

**Decision.**
- Python: `uv` (project, lockfile, `uv run`), ruff (lint + format), mypy (`--strict` on `domain`, `categorisation`, `parsers.sdk`, `services`), import-linter (layer contracts), pytest 8 + pytest-asyncio + Hypothesis 6 + pytest-socket, httpx (ASGI test client), reportlab 4 (dev-only, fixtures), Locust 2 (load tests, dev-only).
- Frontend: npm with a lockfile, oxlint (the Vite template default; fast, zero-config), Prettier 3, Vitest 5 + Testing Library, Playwright 1.x (from M2).
- Containers: Docker + Compose v2. A single multi-stage Dockerfile builds one image used for the api, worker and beat roles.
- pre-commit runs ruff, prettier and the no-private-data check.
