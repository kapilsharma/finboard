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
Done on 2026-11-04 in a cloud session: CI (contract suite on 3 OSes, `e2e` job) mirrored in
`scripts/ci-local.sh` (green end to end), ROADMAP M2 marked done, ADR-0033 and ADR-0034,
ARCHITECTURE §3/§8/§15, CONTRIBUTING › How to add your bank. Left: open the PR (`Closes #2`)
and get CI green on it.

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
