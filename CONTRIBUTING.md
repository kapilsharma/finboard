# Contributing

Thanks for helping! Start with [README.md](README.md) for setup and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit.

## Ground rules

1. **No real financial data, ever.** Not in code, tests, fixtures, issues or screenshots. Use the
   synthetic fixture builders, and redact anything you paste.
2. **Respect the layers** (`api → services → db → domain`). `uv run lint-imports` checks them.
3. **Every user-owned table gets row-level security.** Add `user_id`, a `(user_id, id)` unique key,
   composite foreign keys, and `enable_user_rls()` in the migration. Add the table to
   `USER_OWNED_TABLES`. The tenancy tests fail if you forget.
4. **Money is `Decimal` / `NUMERIC(14,2)`**, never float. It crosses the API as a decimal string.
5. Significant design changes get a short ADR in `docs/adr/`.

## Before opening a pull request

Run `bash scripts/ci-local.sh` (Windows: `powershell -File scripts\ci-local.ps1`). It runs the same checks
as CI, including the Playwright e2e test. The individual commands are:

```sh
cd backend  && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run lint-imports && uv run pytest
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm test
```

If you changed the API, run `npm run gen:api` in `frontend/` and commit `src/api/schema.d.ts`.

## How to add your bank

An adapter turns one bank's statement format into Finboard's canonical `ParsedStatement`
(ARCHITECTURE §8). You never need to share a real statement to write one: you work from its
*layout*, and the tests run on fake data drawn in that layout.

1. **Look at the layout, safely.** Run this on your own machine:

   ```sh
   cd backend && uv run finboard inspect-layout path/to/statement.pdf
   ```

   It prints the page structure with every digit shown as `9` and every letter as `X`. It asks
   for the password if the PDF is encrypted, and reads the file locally only. Check the output
   before you paste it anywhere (an issue, a chat).
2. **Copy the template.** Copy `backend/src/finboard/parsers/builtin/_template/` to
   `backend/src/finboard/parsers/builtin/<bank>_<account>_pdf/` (for example `kotak_savings_pdf`).
   It is a complete, tested adapter for a made-up "Example Bank", so start from working code.
   Rename the classes and set `id`, `name`, `version`, `institutions` and `account_types`.
3. **`detect(doc)`** returns 0.0–1.0, cheaply, and never raises. Look for text that only this
   bank's statements have (a header, a footer, an IFSC prefix). Your own statements should score
   at least 0.8, other banks' below 0.5. Don't set `fallback`: that is only for generic parsers
   ([ADR-0033](docs/adr/0033-fallback-parsers-and-fixture-discovery.md)).
4. **`parse(doc, options)`** returns a `ParsedStatement`. Amounts are positive `Decimal`s with a
   `direction`; set `balance_kind="liability"` for credit cards and loans; `account_hint` is at
   most the last 4 digits. Use the helpers in `finboard.parsers.sdk.helpers` (`parse_amount`,
   `parse_date`, `last_digits`). When the layout isn't what you expect, raise
   `ParserError("…")` with a message that is safe to show the user: no statement values in it.
   Parsers are pure and synchronous: no database, no network, no logging of statement content.
5. **Write `fixtures.py`.** It draws the same layout with reportlab, using fake data from
   `synthetic_statement(...)`, and returns the PDF bytes with the `ParsedStatement` your parser
   must produce. Copy positions, labels and number/date formats from the masked layout. Never
   copy real values, and never commit a PDF.
6. **Register both entry points** in `backend/pyproject.toml`, under the same name as the
   parser's `id`:

   ```toml
   [project.entry-points."finboard.parsers"]
   kotak_savings_pdf = "finboard.parsers.builtin.kotak_savings_pdf.parser:KotakSavingsParser"

   [project.entry-points."finboard.parser_fixtures"]
   kotak_savings_pdf = "finboard.parsers.builtin.kotak_savings_pdf.fixtures:KotakSavingsFixtures"
   ```

   Then run `uv sync` so the entry points are installed, and `uv run finboard parsers` to see
   your adapter in the list.
7. **Run the contract suite:**

   ```sh
   cd backend && uv run pytest tests/parsers
   ```

   It picks up your adapter automatically and checks detection against every other adapter,
   exact parse results for several seeds (including empty and multi-page statements),
   reconciliation, the encrypted variant and determinism. It runs on Linux, macOS and Windows,
   with no database.
8. **Try it on your real statements, locally.** Start the app (`uv run finboard dev`) and import
   a few of your own statements. They should all reconcile, and importing them again should skip
   every row. In the pull request, say that you did this. Don't attach the statements, screenshots
   of them, or the unmasked layout.

Adapters can also live in their own package: register the same two entry-point groups in that
package's `pyproject.toml`. While you develop one, `FINBOARD_EXTRA_PARSERS='["my_pkg.parser:MyParser"]'`
loads it without packaging.
