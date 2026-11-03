# Architecture Decision Records

Each ADR is short: Status · Context · Decision · Consequences.
Status values: **Accepted (given)** = fixed by HANDOVER §2 · **Accepted** · **Proposed** · **Proposed change** = deviates from the handover and needs owner sign-off · **Superseded**.

| # | Title | Status |
|---|---|---|
| [0001](0001-local-web-app-loopback.md) | Local web app on 127.0.0.1 | Accepted (given), amended by 0021 |
| [0002](0002-python-fastapi-backend.md) | Python + FastAPI backend | Accepted (given) |
| [0003](0003-react-typescript-vite.md) | React + TypeScript (Vite) | Accepted (given) |
| [0004](0004-sqlite-in-user-data-dir.md) | SQLite in user data dir | ~~Accepted (given)~~ Superseded by 0022 |
| [0005](0005-no-ai-deterministic-rules.md) | No AI; deterministic rules | Accepted (given) |
| [0006](0006-inr-locale-and-mit-licence.md) | INR / en-IN; MIT | Accepted (given) |
| [0007](0007-orm-sqlalchemy2-sync.md) | SQLAlchemy 2 sync | Superseded by 0023 |
| [0008](0008-money-numeric-decimal.md) | Money: NUMERIC(14,2) / Decimal / strings | Accepted (revised) |
| [0009](0009-parser-discovery-entry-points.md) | Parser discovery via entry points | Accepted |
| [0010](0010-parse-in-child-process.md) | Parse in child process | Superseded by 0024 |
| [0011](0011-preview-state-in-staging-tables.md) | Preview state in DB staging tables | Accepted (revised) |
| [0012](0012-charts-d3-react-svg.md) | d3 maths + React SVG charts | Accepted |
| [0013](0013-state-tanstack-query-url.md) | TanStack Query + URL state | Accepted |
| [0014](0014-openapi-generated-ts-types.md) | TS types from OpenAPI | Accepted |
| [0015](0015-dev-proxy-no-cors-csrf-header.md) | Vite proxy, no CORS; CSRF header guard | Accepted (owner) |
| [0016](0016-transaction-fingerprint.md) | Transaction fingerprint | Accepted |
| [0017](0017-signed-metric-sums-refunds.md) | Signed metric sums; refunds reduce spending | Accepted (owner) |
| [0018](0018-python-tooling-uv-ruff-mypy.md) | Tooling | Accepted (revised) |
| [0019](0019-styling-css-modules.md) | CSS Modules + CSS variables | Accepted |
| [0020](0020-regex-rules-with-timeout.md) | Regex rules with a timeout | Accepted |
| [0021](0021-multi-user-ready-single-user-first.md) | Multi-user-ready, single user first | Accepted (owner) |
| [0022](0022-postgresql.md) | PostgreSQL 18 only | Accepted (owner) |
| [0023](0023-async-sqlalchemy.md) | Async SQLAlchemy, UoW, repositories | Accepted (owner) |
| [0024](0024-celery-redis-jobs.md) | Celery + Redis background jobs | Accepted (owner) |
| [0025](0025-tenant-isolation-rls.md) | Tenant isolation: user_id, composite FKs, RLS | Accepted |
| [0026](0026-blob-storage.md) | BlobStore abstraction | Accepted |
| [0027](0027-statement-password-handoff.md) | Ephemeral encrypted password handoff | Accepted |
| [0028](0028-uuidv7-primary-keys.md) | UUIDv7 primary keys | Accepted |
| [0029](0029-observability.md) | Observability without telemetry | Accepted |
