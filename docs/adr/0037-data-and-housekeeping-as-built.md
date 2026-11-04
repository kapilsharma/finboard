# ADR-0037: Your data and housekeeping as built (M5)

**Status:** Accepted (2026-11-04, M5 / issue #5). Refines ARCHITECTURE §6, §10, §13 and §16, [ADR-0025](0025-tenant-isolation-rls.md) and [ADR-0026](0026-blob-storage.md).

**Context.** M5 gives users control of their data (export, import, delete-all, CSV) and adds housekeeping jobs. Issue #5 asked for the housekeeping to "run as a maintenance role that is allowed across users". Building it settled that and several details of the export format.

**Decisions.**

1. **Housekeeping runs per user, under row-level security, not as a cross-user role.**
   - `maintenance.expire_staged` (hourly), `maintenance.requeue_stale` (every 5 minutes) and `maintenance.purge_jobs` (daily) list the user ids in `app_user`, which holds no financial data and has no RLS. Then they do their work in one unit of work per user, bound to that user, exactly like a request.
   - **Why not a privileged role:** a role with `BYPASSRLS` (or a policy exception) would be the one piece of the system that can read everyone's transactions. The roles are created by `deploy/postgres/init/01-finboard.sh`, which runs only on an empty volume, so existing databases would never get it. Per-user work costs one small transaction per user: fine for hundreds of users.
   - A failure for one user is logged and skipped; the others still run.
   - `finboard beat` runs the schedule, and exactly one beat should run.
2. **Export format (version 1).** One zip:
   - `manifest.json`: format, version, app version, counts, a SHA-256 per table (of the canonical JSON of its rows) and a SHA-256 per file;
   - `data.json`: every user-owned row, column by column, generated from the table definitions, so a new column is never silently left out;
   - `pdfs/<import id>.pdf`: the archived statements, still bank-encrypted.

   Jobs and staged rows are transient and aren't exported. Imports that are still in progress (uploaded, queued, processing, needs password, parsed) aren't either: their only lasting data would be staged rows.
3. **Import keeps ids.**
   - Transaction fingerprints contain the account id, so a restored Finboard still recognises statements it has already seen, and blob keys are rewritten for the importing user.
   - If the ids already exist in the database (another user holds the same data), the insert fails and the import is refused with a clear message, rather than remapping every id and recomputing fingerprints.
   - Import only goes into a Finboard with no accounts, transactions or imports. It replaces the default categories, rules, budgets and settings.
4. **The import zip is untrusted (§13). Everything is validated before anything is written:**
   - only `manifest.json`, `data.json` and `pdfs/<uuid>.pdf`;
   - no directories, symlinks or duplicate names;
   - size limits per member and in total;
   - a compression-ratio limit (zip bombs), with members read in chunks without trusting their headers;
   - a known format and version (a newer version is refused with "update Finboard first");
   - exactly this version's tables and columns, each value of the right type (money as decimal strings, never floats);
   - every table and file checksum.
5. **Delete-all** (`data.delete_user_data`, behind the typed confirmation "DELETE ALL") deletes the caller's rows (both the user filter and RLS apply) and their blob prefix `users/<id>/`. It keeps its own job row, then seeds the default categories and starter rules again so the app stays usable.
6. **CSV** (`GET /data/transactions.csv`): one row per transaction with category paths. Cells starting with `=`, `+`, `-`, `@`, a tab or a carriage return get a leading apostrophe, so a spreadsheet won't run a description as a formula.
7. **Pre-migration backup** (§16).
   - **When:** `finboard serve` takes a `pg_dump -Fc` into `FINBOARD_BACKUP_DIR` (default `.devdata/backups`) only when the database is at an older revision. A fresh database needs no backup.
   - **The password** goes in `PGPASSWORD`, never on the command line.
   - **Failures:** if `pg_dump` isn't installed, a warning is logged and the migration goes ahead (dev machines). If it is installed but fails, for example a client older than the server, the migration stops; `FINBOARD_BACKUP_BEFORE_MIGRATE=false` overrides that. The M7 image must ship a `pg_dump` that matches Postgres 18.
8. **Settings tabs.** The System tab became part of Data ("Check worker"), and `/settings/system` still opens it. Parser options are edited through a form generated from each adapter's JSON Schema, and the server validates them again with the adapter's Pydantic model.
9. **Budget lookup** is one pure function (`domain/budgets.py`), used by the dashboard and the Budgets API alike, instead of the SQL `DISTINCT ON` used in M4. The budget table is a few rows per category.

**Consequences.** Moving to a new machine is export → install → import. A restore into the same database works after delete-all. Restoring someone else's export into a second user of the same database needs id remapping, which isn't supported. Exports are built in memory, which is fine for one person's statements; streaming to a temporary blob is the next step if exports ever grow large.
