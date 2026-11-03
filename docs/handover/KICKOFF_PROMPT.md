# Kickoff prompt for Claude Code

Copy everything below the line into Claude Code, started in an empty repo folder
that contains this `finboard-handover/` folder.

---

You're the architect for **Finboard**, a private, local-first personal finance app
(React + TypeScript frontend, Python FastAPI backend, SQLite) that imports
password-protected **PDF bank statements** through **bank-specific parser plugins**,
categorises transactions **from their description using user-editable rules (no AI)**,
and shows a dashboard. It will be open-sourced; the owner's data must never be.

**Read first, in this order:**
1. `finboard-handover/HANDOVER.md` — requirements, decisions already made, domain model sketch, parser contract, open questions.
2. `finboard-handover/design/dashboard-mockup.png` and `dashboard-mockup.html` — the approved dashboard (open the HTML in a browser if you can; it works offline).
3. `finboard-handover/design/sample-transactions.csv` and `budgets.csv` — the data shape.

**Your task in this session: architecture only. Do not write application code yet.**

Produce these files, then stop and ask me to review:

1. `docs/ARCHITECTURE.md`
   - System overview diagram (Mermaid): browser ↔ FastAPI ↔ SQLite, the import pipeline, the parser registry, the categorisation engine.
   - Repo layout (monorepo tree with `backend/`, `frontend/`, `docs/`, test folders) and what lives where.
   - Backend modules and their responsibilities and boundaries (API layer, services, domain, persistence, parsers, categorisation), and which depend on which.
   - Data model: tables, columns, types, keys, indexes, constraints. Include the transaction fingerprint for dedupe and how money is stored (no floats).
   - Import pipeline as a sequence diagram: upload → decrypt → detect → parse → reconcile → match account → dedupe → categorise → preview → commit / rollback. Include where state lives between preview and commit.
   - Parser plugin system: the final interface, discovery (built-in + entry points), versioning, error handling, and the synthetic-fixture testing approach.
   - Categorisation engine: description normalisation, rule matching order, constraints, manual vs rule provenance, re-apply semantics, rule-from-review suggestions, transfer pairing.
   - REST API outline: endpoints, request/response shapes for the main flows (import, review, transactions with filters, dashboard aggregates, settings CRUD, backup).
   - Frontend architecture: routes/pages (Dashboard, Transactions, Review, Import, Settings tabs), state and data fetching, component breakdown for the dashboard sections in the mockup, charting approach, theming (light/dark), number formatting (`en-IN`, ₹, lakh grouping).
   - Metric definitions as one shared spec (where the code that computes them lives).
   - Security and privacy measures (127.0.0.1 binding, Host check, password handling, data dir, no telemetry).
   - Testing strategy (pytest, Vitest, Playwright; parser contract tests; reconciliation test) and CI matrix.
   - Developer and user run experience (dev mode with two servers vs single-port production mode).
2. `docs/adr/` — one short ADR per significant choice (e.g. ORM, money representation, parser discovery, chart library, state management, preview-session storage). Mark the ones the handover already fixed as "Accepted (given)".
3. `docs/ROADMAP.md` — milestones that refine section 9 of the handover. Each milestone gets acceptance criteria and the tests that prove it.
4. `docs/OPEN_QUESTIONS.md` — the handover's open questions plus any new ones. For each, give your recommended default so work isn't blocked.

**Constraints:**
- Respect the decisions in HANDOVER.md §2. If you think one is wrong, say so in an ADR marked "Proposed change" rather than silently deviating.
- Keep v1 scope as in §8: no AI, no auth, no cloud, no email fetching. Leave an extension point for a future "import folder watcher".
- Prefer boring, well-maintained libraries. Pin major versions in the docs.
- No real bank data anywhere in the repo, ever. Fixtures are generated.
- Keep docs concise and skimmable. Use diagrams where they replace paragraphs.

When the docs are written, summarise the key decisions and trade-offs in under 15 bullets and list anything you need me to decide. **Wait for my approval before scaffolding the project.**
