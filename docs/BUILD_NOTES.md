# Build notes: what was built, and where it deviates

One place to read what each milestone delivered and how it differs from the plan. It
collects the end-of-milestone summaries; the details and the reasons live in the ADRs linked
below, and each milestone's acceptance table in [ROADMAP.md](ROADMAP.md) is still the
definition of done.

| Milestone | Issue | ADRs |
|---|---|---|
| [M2 Import pipeline](#m2-import-pipeline) | #2 | [0033](adr/0033-fallback-parsers-and-fixture-discovery.md), [0034](adr/0034-parse-cap-and-hard-kill.md) |
| [M3 Categorisation](#m3-categorisation) | #3 | [0035](adr/0035-categorisation-as-built.md) |
| [M4 Dashboard and transactions](#m4-dashboard-and-transactions) | #4 | [0036](adr/0036-dashboard-as-built.md) |
| [M5 Settings and your data](#m5-settings-and-your-data) | #5 | [0037](adr/0037-data-and-housekeeping-as-built.md) |
| [M3a Category suggestions](#m3a-category-suggestions) | #6 | [0038](adr/0038-ai-suggestions-as-built.md) |
| [M4a Ask Finboard](#m4a-ask-finboard) | #7 | [0039](adr/0039-ask-finboard-as-built.md) |

---

## M2 Import pipeline

### What's built
- **Backend:** the full import pipeline from ARCHITECTURE §7 and §10: upload, worker parse, unlock, preview, commit, discard, rollback. It also includes the parser SDK, the `generic_table` adapter, and a working `_template` adapter for contributors.
- **Tests and CLI:** the parser contract suite, the new tables with row-level security, and the CLI commands `finboard init`, `finboard parsers` and `finboard inspect-layout`.
- **Frontend:** the Import page, Settings › Parsers and Settings › Import history, checked in light, dark and at 400 px.
- **End-to-end:** a Playwright test (encrypted upload → unlock → commit → re-import skipped) against `finboard serve` with a real worker.
- **CI:** the contract suite runs on Linux, macOS and Windows; an e2e job; both mirrored in `scripts/ci-local.sh`.
- **Bugs found and fixed along the way:**
  - A slow parse was reported as "No parser recognised": the registry swallowed Celery's soft time limit inside `detect()`.
  - In dev mode, tracebacks printed local variables, which could include a password or statement text.
  - `12,34` was read as an amount (1234).
  - Buttons with visually hidden label text had wrong accessible names (e.g. "Roll backsept.pdf").

### Deviations
- **ICICI adapter:** `icici_savings_pdf` isn't in M2. It's issue #9, which needs the owner's statement layout, and the ROADMAP row "owner imports 3 real ICICI statements" moved there.
- **Frontend test mocking:** Vitest uses the existing `mockApi` fetch stub, not MSW.
- **E2E setup:** the e2e test runs against `finboard serve` plus a worker on the `finboard_test` database, not the M7 compose stack.
- **Fallback parsers** rank below bank-specific ones, and fixture builders are discovered through the `finboard.parser_fixtures` entry points (ADR-0033).
- **Parse cap:** each user has at most 2 parses running; extra uploads wait as `uploaded`. A parse killed by the hard time limit is recorded by `Request.on_timeout` (ADR-0034).
- **Reconciliation** uses the account's type (credit card or loan = liability) once the account is known, otherwise the parser's `balance_kind`. A break in the running balance is a mismatch even when the totals agree.
- **Account and category deletes** return 409 while in use.
- **No temp files:** uploads are kept in memory, so a statement is never spooled to a temp file.

---

## M3 Categorisation

### What's built
- **Rules at import time:** rules propose a category for each preview row, then decide again at commit, keeping categories chosen by hand. Each rule counts its hits.
- **Matching:** "contains", "starts with", "is exactly" and regular expressions, on descriptions with reference numbers, card masks and IFSC codes stripped. A regex that takes over 50 ms is switched off, and Settings › Rules shows why.
- **Re-apply** runs as a background job with a dry-run preview first. It never overwrites confirmed transfers, and only overwrites manual choices if asked.
- **Review page:** uncategorised transactions grouped by merchant, with bulk categorise. Saving a category can create a rule, with a live "would match N" count, and then asks "Apply to N uncategorised?" (OQ-12).
- **Transfers between own accounts:** suggested after every import and confirmed by the user, never automatically (OQ-6): Card payment if a credit card is involved, otherwise Own transfer.
- **Settings › Rules:** drag to reorder, or up/down buttons (which work without a mouse), plus search, on/off switches, test before saving, and YAML/JSON import and export.
- **Starter rules** for common Indian merchants; SIPs, LIC, ATM withdrawals and EMIs follow OQ-2, 17, 25 and 26.
- **Speed:** re-applying 200 rules to 50,000 transactions takes about 5 s in a worker (budget 10 s).
- **Checks:** light, dark and 400 px; tenancy tests for rules, transfers and transactions.

### Deviations
- **Rule suggestions** use the first merchant word of a description, not the longest. Narrations put the merchant before the city ("RELIANCE FRESH BANGALORE IN" → RELIANCE, not BANGALORE).
- **Rejected transfer pairs are remembered,** so they're never suggested again; that needs partial unique indexes instead of a plain `UNIQUE`. Undoing a confirmed pair, or recategorising one side of it by hand, marks it rejected and lets the rules categorise both sides again.
- **Account movement:** rows in loan, insurance and mutual-fund accounts default to Account movement and need no review (OQ-25).
- **Deleting a rule** keeps the categories it gave (`rule_id` is set to NULL).
- **Existing users** add the starter pack with `POST /rules/starter-pack` or the button; new users get it automatically.
- **The re-apply perf test** lives in `tests/integration/perf/`, because it needs the database fixtures.

---

## M4 Dashboard and transactions

### What's built
- **Golden figures:** the handover sample gives exactly the approved September 2026 figures: Income ₹1,42,702.04, Spending ₹96,040.38, Net ₹46,661.66, Rate 32.7 %, Δ net −₹22,330.28, Invested ₹15,000, 2 categories over, review count 2. The test runs through the real SQL, metrics and API.
- **Backend:**
  - one metrics module as the single source of truth, with the definitions served as tooltips;
  - monthly budgets;
  - a dashboard endpoint where an unchanged dashboard is a 304;
  - `/transactions` with filters, search, sorting on any column, cursor paging and totals;
  - `finboard demo-data` for the synthetic sample.
- **Frontend:**
  - every mockup section, including the two small fixes the handover asked for: axis labels read ₹50K / ₹1L, and over-limit text reads "₹94 over" with no minus sign;
  - filters kept in the URL, so they survive month changes and reloads;
  - inline re-categorise from the transaction table;
  - a Transactions page for any date range that renders only the visible rows.
- **Accessibility:** axe finds no WCAG 2.1 AA issues in light or dark mode, and there's no horizontal page scroll at 400 px.
- **Performance:**
  - dashboard p95 87 ms (budget 200 ms) for a user with 50,000 transactions in a 100-user database;
  - a `/transactions` page 20 ms (budget 100 ms);
  - Locust with 200 users: p95 57 ms with 3 API processes, 930 ms with one, which saturates.

### Deviations
- **Limits summary:** "left" is total limits minus total spent (₹5,810), as in the approved mockup. ARCHITECTURE §12 said Σ max(remaining, 0), which hides overspends.
- **Percentages** are rounded once, to one place, on the server. Rounding twice turned −11.2504 % into −11.2 % where the mockup shows −11.3 %.
- **Test locations:** the golden, perf and ETag tests live under `tests/integration/`. E2E runs against `finboard serve` with the demo data, not the M7 compose stack.
- **API processes:** `finboard serve --workers N` was added for the load budget; the default stays 1, and M7 should set it.
- **Visual sign-off** by the owner against the mockup: screenshots in `docs/screenshots/`.

---

## M5 Settings and your data

### What's built
- **Settings › Budgets:** each expense category's limit this month with its history. Change a limit from a month, or undo a change; earlier months are unaffected.
- **Category merge:** moves transactions, rules and budgets, then deletes the old category.
- **Settings › Parsers:** switch each parser on or off, and edit its options through a form generated from its schema. A switched-off parser is never picked automatically, and saved options reach the parser.
- **Settings › Data** (replaces System):
  - export everything as one zip, then download it;
  - import an export into an empty Finboard;
  - transactions as CSV, with formula-like cells neutralised;
  - delete-all behind typing "DELETE ALL";
  - the worker check.
- **Housekeeping, run by `finboard beat`:** expire stale previews (hourly), re-queue stuck jobs (every 5 minutes), purge old jobs and exports (daily).
- **Pre-migration backup:** `finboard serve` runs `pg_dump` before migrating an older database. The password goes through `PGPASSWORD`, never the command line.
- **Tests:**
  - export → delete-all → import gives an identical dataset (counts and checksums), the same statement files, and still recognises a re-uploaded statement;
  - malicious zips are rejected: traversal, extra files, symlinks, a newer version, tampered data, money as floats, zip bombs;
  - delete-all is tenant-scoped.

### Deviations
- **Housekeeping runs one user at a time, under that user's row-level security,** instead of as a cross-user maintenance role. Such a role would be the only thing able to read everyone's data, and existing databases could never get it, because the roles are only created when the database volume is first set up.
- **Imports keep their original ids,** so a restored Finboard still recognises statements it has seen. Restoring an export into a second user of the same database, while the first still has the data, isn't supported and is refused clearly.
- **The backup is skipped if `pg_dump` isn't installed,** with a warning. A `pg_dump` that is installed but fails stops the migration; `FINBOARD_BACKUP_BEFORE_MIGRATE=false` overrides that. The M7 image needs a `pg_dump` that matches Postgres 18.
- **Settings › System** became part of Settings › Data; old links still work.

---

## M3a Category suggestions

Optional and off by default: the operator makes it available (`FINBOARD_AI_SUGGESTIONS=on`, the `ai` extra, `finboard ai fetch-model`), and each user turns it on in Settings › AI.

### What's built
- **Embeddings, all local:**
  - all-MiniLM-L6-v2 through fastembed (ONNX, no PyTorch). It is downloaded once by `finboard ai fetch-model` and then runs offline.
  - Vectors are stored in `txn_embedding` (pgvector, RLS).
  - `ai.embed` runs after each import commit and `ai.embed_all` when the feature is turned on, on their own `ai` queue.
- **Suggestions:**
  - the 10 nearest categorised transactions (by rule or by hand, same direction) vote, weighted by similarity;
  - up to 3 categories, each with its closest examples as the "why";
  - transactions not yet embedded fall back to trigram similarity.
- **UI:**
  - Settings › AI: both switches, a plain statement of what leaves the machine, embedding progress, and clearing question history.
  - The categorise dialog shows suggestions with **Accept** (a manual categorisation) and **Make a rule**.
- **Evaluation** (`finboard ai eval-suggestions` → [ai-eval.md](ai-eval.md)):
  - generated variants a rule would miss, plus never-categorised merchants;
  - parameters tuned on one seed, scored on four others.
  - Held-out top-1: **0.948** for MiniLM, 0.953 for bge-small (within noise), 0.764 for the trigram baseline.
- **Speed:** 5,000 transactions embedded in 6.5 s, 454 MB peak (budget 60 s, 600 MB).
- **Bugs found and fixed along the way:**
  - The "too different to vote" cut-off was an untested guess, and it hid an obvious match in the demo data. Narration boilerplate made unrelated merchants look alike, so now only merchant words are embedded, and the cut-off is calibrated with merchants the user never categorised.
  - Delete-all didn't remove the new AI tables.
  - The API didn't start without the `ai` extra.

### Deviations
- **Embedded text** is the merchant words, not the whole normalised description. Vectors carry a text version, so they're rebuilt when the rules change.
- **Baseline:** pg_trgm trigram similarity, which is also the production fallback, instead of TF-IDF or `rapidfuzz`.
- **pgvector:**
  - image `pg18-trixie` (the bookworm `pg18` tag breaks the collation on existing volumes);
  - the superuser creates the extension (`scripts/enable-pgvector.sh` for existing databases);
  - our own `Vector` column type.
- **Suggestions** appear in the categorise dialog, not inline in the review groups.
- **Export** leaves out the AI tables (derived data and a question log). Delete-all removes them.
- **Unit tests** may open Unix sockets (asyncio needs them). Network sockets stay blocked.

---

## M4a Ask Finboard

Optional and off by default: the operator sets `FINBOARD_AI_ASK=gemini|ollama` (and `FINBOARD_AI_ASK_SQL` for the SQL path), and each user opts in.

### What's built
- **Spec path:**
  - the model fills a `QuerySpec` (metric, categories, accounts, merchant, dates, grouping, chart hint);
  - a deterministic builder turns it into SQL on the dashboard's metric definitions;
  - the SQL runs in Postgres on a READ ONLY connection, under RLS, with a 3 s timeout.
  - The golden question matches the dashboard to the paisa.
- **SQL path** (off by default):
  - one guarded SELECT (sqlglot allow-lists, then transpiled to SQLite);
  - it runs in a fresh in-memory SQLite database holding only the caller's rows, with an authorizer, `query_only`, a 3 s cut-off and a 1,000-row cap.
- **LangGraph graph:** understand → spec or generate → guard → execute → chart → answer, or a clarifying question, with at most 2 retries carrying locally written hints. Rows stay in a per-request store, never in the graph state.
- **One outbound module** (`ai/llm.py`):
  - a typed, allow-listed request carrying the question, catalog, category paths, account aliases and today's date;
  - Gemini Flash by default, Ollama as the local option;
  - 429s and timeouts become `ai_unavailable`.
- **API:** `POST /ask`, `GET`/`DELETE /ask/history`, `POST /ask/{id}/pin`, `GET /dashboard/widgets`, `DELETE /dashboard/widgets/{id}`. Every route is a 404 (`ai_off`) unless the feature is available and the user opted in.
- **UI:**
  - The Ask panel sits below the mockup's sections, with the provider disclosure, a chart or table, "show query" and Pin.
  - Pinned widgets re-run locally with no model call. A stale catalog shows "needs updating".
  - Checked in light, dark and at 400 px: screenshots `docs/screenshots/ai-*.png`.
- **Evaluation:** `finboard ai eval` runs 31 golden questions over the demo data and writes to `docs/ai-eval.md`. An oracle-model test proves every reference answer runs.
- **Tests:**
  - privacy canaries (descriptions, amounts, account names) through the real LangChain client, including retries;
  - the guard attack corpus plus Hypothesis;
  - sandbox escapes (ATTACH, PRAGMA, writes, extensions, recursion, timeout, row cap);
  - no rows in any graph state;
  - tracing forced off;
  - tenancy.
- **Bugs found and fixed along the way:** the guard rejected every query containing `AND`, because sqlglot models operators as functions. The oracle test caught it.

### Deviations
- **Model replies** are JSON validated locally, not provider structured output. The same code serves Gemini, Ollama and recorded replies.
- **Money:** the model names money output columns `*_paise`, and the app converts them to rupees.
- **History:** `DELETE /ask/history` clears unpinned questions; there's no per-item delete.
- **CI:** the lint and integration jobs install the `ai` extra. The cross-OS unit job checks the app without it.
- **Pending:**
  - the live `finboard ai eval` run (needs the owner's `FINBOARD_GEMINI_API_KEY`), which decides the "≥ 80 % spec-path accuracy" row;
  - the owner's laptop perf run for M3a;
  - the README demo GIF.
