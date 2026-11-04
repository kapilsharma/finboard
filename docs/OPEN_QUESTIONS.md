# Open questions

Revision 4 (2026-11-04: AI questions added). Each open item has a **recommended default**, so work proceeds unless Kapil says otherwise. Resolved items are kept for the record.

## Resolved

| # | Question | Answer |
|---|---|---|
| OQ-1 | Which banks? | **Savings:** ICICI, Yes, CSB, Kotak, HSBC. **Credit card:** ICICI. **Home loan:** HDFC. **Investments:** 13 MF SIPs (one category). **Insurance:** LIC. **First adapter: ICICI savings** (in M2), others later (M6) |
| OQ-2 | MF: one category or per fund? | **One "Investments" category** |
| OQ-3 | Text PDFs or scans? | **PDFs emailed by the banks** → text PDFs. No OCR |
| OQ-4 | Refunds? | **Original category**: a refund reduces that category's spending ([ADR-0017](adr/0017-signed-metric-sums-refunds.md)) |
| OQ-5 | Archive PDFs by default? | **Yes** (original encrypted file) |
| OQ-13 | Docker in v1? | **Yes**, it's the standard run |
| OQ-15 | DB encryption at rest? | **OS disk encryption is enough** |
| OQ-20 | Real adapters early? | **Yes**: ICICI savings ships in M2 |
| OQ-21 | Email fetching / saved passwords? | **Neither.** The user downloads statements from email and uploads them, entering the password each time. Nothing is stored ([ADR-0027](adr/0027-statement-password-handoff.md)) |
| OQ-26 | LIC premiums: expense or investment? | **Expense**: seed category *Insurance* (type expense) |
| OQ-27 | Order of remaining adapters | **ICICI CC → Kotak → HSBC → Yes → CSB** savings |
| — | ADR-0015 (proxy, no CORS, CSRF header) | **Accepted** |
| — | Async / multi-user / DB / jobs | Async; multi-user ready, single user first; PostgreSQL; Celery + Redis |
| OQ-29 | AI in Finboard? | **Yes, optional and assistive** (2026-11-04). Finboard becomes the Python + AI portfolio project instead of a separate RAG demo. Rules stay authoritative, and the LLM never sees transaction data ([ADR-0030](adr/0030-assistive-ai-opt-in.md)) |
| OQ-30 | Which LLM? | **Gemini Flash on the free tier** (owner checked it's free to start). Provider kept swappable (LangChain). Ollama as an optional offline fallback |

## Open

| # | Question | Recommended default | Blocks |
|---|---|---|---|
| **OQ-25** | Home loan (HDFC): how should it count? | **The EMI debit from savings is an expense, *Loan EMI*** (as in the mockup). An HDFC loan statement isn't needed for v1. If imported later, it goes to a `loan` account and its rows are *Account movement* (transfer), so nothing is double counted. Splitting interest (expense) from principal (saving) is a v2 idea | M3 seed |
| **OQ-28** | Getting the ICICI layout without real data in the repo | You run `finboard inspect-layout statement.pdf` locally (M2). It prints the page structure with every digit as `9` and letter as `X`. You share that output (or describe the columns), and I build a synthetic fixture from it. The real PDF never leaves your machine | M2 |
| OQ-6 | CC bill payment pairing: auto-confirm or suggest? | **Suggest.** Rules still mark `CC BILL PAYMENT` as Card payment (transfer) | M3 |
| OQ-7 | Budgets by parent or leaf category? | **Leaf**; a parent budget covers its children | M4 |
| OQ-8 | Cash-flow chart range | **Trailing 12 months** | M4 |
| OQ-9 | Host port | **8765** on 127.0.0.1 | M1 |
| OQ-11 | Manual (cash) transactions in v1? | **No** (schema allows it later) | — |
| OQ-12 | Auto re-apply after saving a rule? | **Ask** "Apply to N uncategorised?" | M3 |
| OQ-14 | Handover files location | Move to **`docs/handover/`** in M1 | M1 |
| OQ-16 | Minimum versions | Python 3.12+ (CI 3.12 + 3.14), Node 22+ (CI 24), PostgreSQL 18, Redis 7 / Valkey 8 | M1 |
| OQ-17 | ATM withdrawals | **Expense › Cash** | M3 |
| OQ-18 | Default category for unmatched credits | Debits → *Uncategorized* (expense); credits → *Uncategorized income*. Both need review | M3 |
| OQ-19 | Package/image name availability | Check before M7; fall back to `finboard-app` | M7 |
| OQ-22 | Tenancy unit: user or household? | **User** in v1 | — |
| OQ-23 | Login method in M8 | Own passwords (argon2id + sessions) first, OIDC later | M8 |
| OQ-24 | Celery prefork unsupported on Windows hosts | Dev worker uses `--pool=solo` on Windows or runs in Docker | M1 |
| OQ-31 | Vector store | **pgvector in the existing Postgres** (`pgvector/pgvector:pg18`): one DB, RLS applies, no extra service on the laptop ([ADR-0031](adr/0031-pgvector-embeddings.md)). Alternatives were ChromaDB, FAISS and Qdrant | M3a |
| OQ-32 | Embedding model | **`all-MiniLM-L6-v2` via fastembed** (384-dim, ~90 MB, CPU/ONNX). Compare with `bge-small-en-v1.5` on the suggestion eval before M3a closes; Indian merchant strings may favour one | M3a |
| OQ-33 | Send result aggregates to the LLM for a written summary? | **No.** Answers come from local templates. Revisit only as a separate, explicit opt-in | M4a |
| OQ-34 | Free-form SQL path on by default? | **Off until the M4a sandbox acceptance tests pass, then on** (`FINBOARD_AI_ASK_SQL`). Review found that Postgres-side limits can be undone by `set_config()` from a SELECT, so model SQL runs only in a per-request SQLite sandbox holding the caller's rows ([ADR-0032](adr/0032-nl-analytics-langgraph.md)) | M4a |
| OQ-35 | Keep Ask history? | **Yes, locally**: question + spec/SQL + timings, never results. Each entry can be deleted, and delete-all covers it | M4a |
| OQ-37 | Account names in prompts? | **No: aliases** (`Account A — savings, ICICI Bank`), mapped back locally. Names can contain employer names or account digits, and the model doesn't need them | M4a |
| OQ-38 | Per-user AI opt-in vs server switch? | **Both**: the operator makes a feature available (env), each user opts in (Settings › AI, default off), following ADR-0021 | M3a |
| OQ-36 | Ollama fallback in v1? | **Optional and documented**, not tested in CI (recorded responses cover the graph). A 1–3B model is the practical limit on a 16 GB laptop | M4a |
