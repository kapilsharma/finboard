# Issue #2 (M2 import pipeline): handover status

Branch `issue-2-import-pipeline`. Last updated 2026-11-04. Delete this file when the PR is merged.

## Done (committed, all green locally)
- Backend: domain money/fingerprint/reconcile; parser SDK; registry; `generic_table` + `_template`
  adapters; contract suite (`tests/parsers`); migration (import_batch, staged_row, txn,
  import_row, RLS); BlobStore + secret handoff; ImportService; `imports.process` task with soft/hard
  limits (custom `Request.on_timeout`); all §10 import endpoints + `GET /parsers`; Idempotency-Key;
  CLI `init`, `parsers`, `inspect-layout`; account/category delete guards.
- Tests: 233 backend tests pass on Windows (py3.14) and Linux (py3.12, Docker), incl.
  `test_parse_timeout.py` (real prefork worker; skipped on Windows). Frontend: 24 Vitest pass.
  Playwright `e2e/tests/import.spec.ts` passes locally against `finboard serve`.
- Frontend: Import page + detail page, Settings › Parsers and › Import history. Checked in
  light, dark and at 400 px (no horizontal page scroll).

## Remaining
1. **CI** (`.github/workflows/ci.yml`):
   - `backend-portable`: run `uv run pytest tests/unit tests/parsers` (the contract suite on all 3 OSes).
   - New `e2e` job (ubuntu, postgres:18 + redis:7 services, run `deploy/postgres/init/01-finboard.sh`
     like backend-integration): `cd frontend && npm ci && npm run build`, then
     `cd e2e && npm ci && npx playwright install --with-deps chromium && npx playwright test`.
   - Mirror both in `scripts/ci-local.sh` (e2e step only without `--fast`; needs `npx playwright
     install chromium` once). Run `bash scripts/ci-local.sh` until green.
2. **Docs**:
   - `docs/ROADMAP.md` M2: mark done (date) and note the deviations below.
   - New ADR-0033 (fallback parsers: a `fallback` attribute ranks generic parsers below
     bank-specific ones; fixture builders are discovered via the `finboard.parser_fixtures`
     entry-point group) and ADR-0034 (per-user parse cap: extra uploads wait as `uploaded` and
     a worker starts them when a slot frees; hard kills are recorded by `ParseTask.Request.on_timeout`).
     Add both to `docs/adr/README.md`.
   - ARCHITECTURE: §3 note on `storage`/`parsers` layers; §8 `fallback` + fixture entry points;
     §15 e2e runs against `finboard serve` (compose stack arrives in M7).
   - `CONTRIBUTING.md` › "How to add your bank": copy `backend/src/finboard/parsers/builtin/_template/`,
     use `finboard inspect-layout`, register both entry points, run `uv run pytest tests/parsers`.
3. **PR**: push, open with `Closes #2`, a summary, and the decisions/deviations list.

## Deviations / decisions to list in the PR
- `icici_savings_pdf` is not in this PR: it's issue #9 (blocked on owner layout). The ROADMAP row
  "owner imports 3 real ICICI statements" moves to #9.
- Vitest uses the existing `mockApi` fetch stub, not MSW (ARCHITECTURE §15 says MSW once mocking grows).
- e2e runs against `finboard serve` + worker on the `finboard_test` DB (emptied first), not the M7
  compose stack.
- Reconciliation uses the account's type (liability for credit_card/loan) once an account is known,
  otherwise the parser's `balance_kind`. A running-balance break is a `mismatch` even when the totals agree.
- Until M3, `description_norm` = the frozen dedupe form, and committed rows go to
  Uncategorized / Uncategorized income with `needs_review`.
- "Possible duplicate" compares new rows against existing txns (same date, direction, amount; different text).
- Account delete: 409 when transactions exist. Category delete: also 409 when in use (txn FK is RESTRICT).
- Bugs found and fixed along the way: the registry swallowed `SoftTimeLimitExceeded` in `detect()`;
  dev console logs printed traceback locals (rich); `12,34` was parsed as an amount; visually-hidden
  button labels produced wrong accessible names.
- Uploads are kept in memory (Starlette `MultiPartParser.spool_max_size` raised) so a statement is
  never spooled to a temp file.

## Environment notes
- On the owner's Windows machine, `uv` is in `%APPDATA%\Python\Python314\Scripts` (not on PATH by default).
- To run the Linux-only timeout test from Windows: run the `ghcr.io/astral-sh/uv:python3.12-bookworm-slim`
  container with the repo mounted, `UV_PROJECT_ENVIRONMENT=/tmp/venv`, and the DB/Redis URLs pointing
  at `host.docker.internal`.
