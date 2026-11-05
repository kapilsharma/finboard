# ADR-0039: Ask Finboard as built (M4a)

**Status:** Accepted (2026-11-05, M4a / issue #7). Refines [ADR-0030](0030-assistive-ai-opt-in.md), [ADR-0032](0032-nl-analytics-langgraph.md) and ARCHITECTURE §18.

**Context.** M4a answers plain-English questions as charts, through a spec path (builder SQL in Postgres) and an optional SQL path (model SQL in a per-request SQLite sandbox). These are the decisions made while building it.

**Decisions.**

1. **Replies are JSON parsed and validated locally**, not provider "structured output".
   - The same code works for Gemini, Ollama (`format="json"`) and recorded replies.
   - `QuerySpec` (Pydantic, `extra="forbid"`) validates the spec. An invalid reply becomes a locally written retry hint naming only the bad fields.
2. **Money in the sandbox is integer paise, and the model says which columns are money.**
   - The catalog exposes `signed_paise` and `limit_paise`, and tells the model to name money output columns `*_paise`.
   - Those columns become `Decimal` rupees locally, with the suffix dropped. Other numbers stay numbers.
   - This keeps sums exact without parsing the model's SQL to work out which columns hold money.
3. **Spec queries run on their own connection.** `SET TRANSACTION READ ONLY` must come before the `set_config` that binds the user for RLS, so the request's own transaction can't be used. A statement timeout becomes `QueryTimeout` (problem+json `query_timeout`, 503).
4. **Guard details.**
   - sqlglot models `AND`/`OR`/`NOT` and other operators as function nodes. The first guard therefore rejected any query with `AND`, which the eval harness's oracle test caught. Operators are now told apart from functions.
   - `date_trunc` (month, year, day) and `extract` (year, month, day) are rewritten into SQLite date functions, because sqlglot leaves them in forms SQLite can't run. `INTERVAL` arithmetic is rejected with a hint to compare the `date` or `month` text.
   - The allow-lists live in `ai/allowlist.py`, shared by the guard and the sandbox's authorizer.
5. **Retries are counted across the graph**: at most 2 for a question, whichever node failed.
6. **The SQL path off means a clarifying reply.** With `FINBOARD_AI_ASK_SQL` off (the default, OQ-34), the "needs SQL" option isn't offered in the prompt. If the model asks for it anyway, the user gets a "try asking for a metric by month, category, account or merchant" reply.
7. **Endpoints.**
   - `DELETE /ask/history` clears every question that isn't pinned. The issue lists this; the ROADMAP's per-item delete was dropped.
   - A widget's chart comes from its `ask_query` row, so `dashboard_widget` has no `chart` column.
   - Pinned widgets re-run when the dashboard loads, with no model call. Pinned SQL is guarded again each time. A catalog-version change or a renamed category shows "needs updating".
8. **The answer sentence is a local template.** It includes Indian-grouped rupee totals. The model never sees results.
9. **Evaluation (`finboard ai eval`).**
   - 31 golden questions run over the synthetic demo data, as a dedicated `ai-eval` user, with `today` fixed to 2026-09-30.
   - Each question has a reference spec or SQL. An answer is correct when its rows equal the reference rows.
   - The command writes its own section of `docs/ai-eval.md` and keeps the suggestion report.
   - A CI test uses an "oracle" model that replies with each reference, which proves every reference runs and that the scoring works.
   - The live run needs the owner's Gemini key and is still to do.
10. **The `ai` extra really is optional.**
    - The first version of the API imported sqlglot at start-up through the Ask service. The guard is now imported lazily, and a unit test starts the app with every AI library blocked.
    - CI: the lint and integration jobs install the extra. The cross-OS unit job stays core-only, and the Ask integration tests are skipped without the extra.

**Consequences.** All the privacy rules of ADR-0030 hold, and tests prove them:
- canary descriptions, amounts and account display names never reach the provider, including on retries;
- no graph state holds result rows;
- retry hints never quote SQLite's error text;
- tracing is forced off.

Spec-path accuracy against the live provider is not measured yet. Until the owner runs `finboard ai eval`, the ROADMAP's "≥ 80 %" row stays open.
