# Finboard — product & technical handover

> Working name: **Finboard**. Rename freely.
> Owner: Kapil. Audience: Claude Code (and future contributors).
> Status: requirements agreed, dashboard design approved, **no code yet**.
> First step for Claude Code: **architecture only** — see `KICKOFF_PROMPT.md`.

---

## 1. What we are building

A **private, local-first personal finance app** for one person who has
3–4 savings accounts, a credit card and investments in several mutual funds.

Every month the banks email **PDF statements** (usually password-protected).
The user imports them into the app, which:

1. Unlocks and parses the PDF with a **bank-specific parser plugin**.
2. Normalises entries into transactions.
3. **Categorises each transaction from its description** using user-editable rules.
4. Puts anything it can't categorise into a **review queue** for the user to decide.
5. Shows a **dashboard**: income, spending, net saving, savings rate, invested,
   spending vs monthly limit per category, per-account totals and a filterable
   transaction list.

The code will be **open-sourced** (MIT intended). The user's data must never be.

---

## 2. Decisions already made (do not re-litigate without a reason)

| Topic | Decision | Why |
|---|---|---|
| Deployment model | **Local web app** on the user's own machine, served on `127.0.0.1` | Bank data stays on the machine; no auth, hosting or server security to manage |
| GitHub Pages / browser-only | **Rejected** | Browser storage is fragile (cleared, per-device, Safari eviction) and there'd be no backend to learn |
| Electron / Tauri | **Not now** | Can wrap the local web app later if wanted |
| Backend | **Python + FastAPI** | PDF table extraction in Python (pdfplumber, camelot, pikepdf) is far ahead of Go. Learning goal: FastAPI |
| Frontend | **React + TypeScript (Vite)** | Learning goal; owner already knows some React |
| Database | **SQLite** (single file in a user data dir) | Zero-ops, durable, easy backup |
| AI / LLM | **None in v1** | Categorisation is deterministic, from the description field only |
| Currency / locale | **INR, `en-IN` formatting** (₹1,42,000; lakh grouping) | Indian bank accounts |
| Licence | MIT (intended) | Open source |

Suggested libraries (Claude Code may propose alternatives with reasons in an ADR):
FastAPI, SQLModel or SQLAlchemy 2 + Alembic, Pydantic v2, `uv`, pdfplumber,
pikepdf, camelot (fallback), pytest, ruff, mypy; React, Vite, TypeScript,
TanStack Query, React Router, d3 or Recharts, Vitest, Playwright for end-to-end tests.

---

## 3. Users & principles

- **Single user, single machine.** No login in v1. Must bind to `127.0.0.1` only.
- **Privacy by default:** no telemetry, no outbound network calls, no cloud sync.
- **Data dir outside the repo**, configurable, defaulting to an OS-appropriate
  location (e.g. `~/.local/share/finboard`, `%APPDATA%\finboard`). It holds
  the SQLite DB and, optionally, archived statement PDFs.
- **Never commit real statements.** Test fixtures are synthetic PDFs generated in tests.
- **PDF passwords are never stored in the DB.** Ask at import time. Optionally
  (setting) save per-account passwords in the OS keychain via `keyring`.
- **Deterministic and explainable:** every auto-categorised transaction records
  *which rule* categorised it.
- **Idempotent imports:** importing the same statement twice must not duplicate anything.

---

## 4. Functional requirements

### 4.1 Accounts
- Types: `savings`, `current`, `credit_card`, `mutual_fund` (or `investment`), `cash`, `other`.
- Fields: display name, bank/institution, type, masked number (last 4 only),
  parser id to use, currency (INR), active flag, colour (optional).
- The user has 3–4 savings accounts plus card(s) and MF folios; the UI must handle N accounts.

### 4.2 Importing statements (PDF first)
Flow: **Upload → (password) → detect parser → parse → preview → review → commit**.

- Upload one or more PDFs (drag-and-drop). Also accept CSV/XLS later via the same plugin system.
- If encrypted: prompt for the password (or use the keychain entry if one is saved). Decrypt in memory with pikepdf.
- **Parser detection:** each parser returns a confidence score for a document;
  the highest above a threshold wins. The user can override the choice and the account.
- **Account matching:** map the statement to an existing account by masked
  number / parser hints. If no match, offer to create an account.
- **Preview** shows the parsed rows, statement period, opening/closing balance and a
  **reconciliation check**: `opening + credits − debits == closing`. A mismatch is a
  warning that blocks commit unless the user overrides it.
- **Duplicate detection:** stable fingerprint per transaction
  (account, date, amount, direction, normalised description, running balance if present,
  per-day sequence number). Re-import skips existing rows and reports how many were skipped.
- Each import is recorded (file hash, parser id + version, period, row counts, time) and
  can be **rolled back** (deletes only that import's transactions).
- Optional setting: archive the original PDF in the data dir.

### 4.3 Parser plugins
See §6 for the contract. The repo ships with:
- a `generic_table` parser (best-effort, for unknown banks) and
- one real parser per bank the owner uses (banks TBD — **open question**).

Contributors can add a bank without touching core code.

### 4.4 Transaction types (drive the maths)
| Type | Meaning | Counted in |
|---|---|---|
| `income` | Money earned (salary, interest, freelance, refunds may be configurable) | Income |
| `expense` | Money spent | Spending, category limits |
| `investment` | Money moved into investments (SIP, MF purchase, FD, PPF) | Invested (not spending) |
| `transfer` | Between the user's own accounts (credit card bill payment, own-account NEFT/IMPS) | **Excluded** from income and spending |

Each category has a default type; a transaction inherits its category's type.

### 4.5 Categorisation (no AI)
- **Categories** are user-editable (name, type, colour, optional parent for grouping,
  e.g. "Investments › Parag Parikh Flexi Cap"). Seed a sensible default set:
  Salary, Interest, Freelance, Refunds, Rent, Loan EMI, Groceries, Dining out,
  Transport/Fuel, Shopping, Utilities, Health, Entertainment, Cash, Investments,
  Card payment (transfer), Own transfer (transfer), Uncategorized.
- **Rules** match on the **description** (plus optional constraints):
  - match kind: `contains` (default), `starts_with`, `equals`, `regex`
  - case-insensitive, applied to a **normalised description** (upper-case, collapsed
    whitespace, UPI/NEFT reference numbers and long digit runs stripped — keep both raw and normalised)
  - optional constraints: account, direction (debit/credit), amount range
  - priority (lower number wins); first match wins
  - outcome: category (and therefore type), optional rename/"payee" label
- **Review queue:** transactions with no matching rule are `needs_review` and
  categorised as `Uncategorized`. In the queue the user picks a category, and the app
  offers to **create a rule** from that choice with a suggested pattern
  (e.g. the merchant token), which can be edited before saving.
- **Re-apply rules** on demand (to all, or only uncategorised) — never overrides a
  **manual** categorisation unless the user asks.
- **Transfer detection helper:** suggest pairing a debit in one own account with a
  credit of the same amount in another own account within ±3 days and mark both as `transfer`.
- Rules are exportable/importable as JSON/YAML so users can share rule packs (no personal data).

### 4.6 Budgets (monthly limits)
- A monthly **limit per category** (expense categories). Optional effective-from month
  so limits can change over time.
- Dashboard shows spent vs limit, remaining (negative = over), and the count of categories over their limit.

### 4.7 Dashboard (design approved — see `design/`)
Open `design/dashboard-mockup.html` in a browser (works offline) and
`design/dashboard-mockup.png`. The mockup runs on the sample CSVs in `design/`.
**Reproduce the layout and behaviour; the implementation is up to you** (React components,
backend aggregation endpoints). Sections, top to bottom:

1. **Header**: title, one-sentence takeaway ("In September 2026 you saved ₹46,662,
   32.7% of your income. Spending was 4.6% higher than Aug. Biggest spend: Rent at ₹32,000."),
   **month selector** (newest first).
2. **Review banner** (only if any): "N transactions in <month> still need a category. Show them →"
   — clicking jumps to the transaction list filtered to *needs review*.
3. **Headline cards** for the selected month, each with change vs previous month
   (coloured good/bad: income up = good, spending up = bad):
   Income · Spending · Net saving · Savings rate (change in percentage points) ·
   Invested (with "x% of net saving").
4. **Cash flow by month**: grouped bars (income, spending) per month + net-saving line;
   selected month highlighted, others faded; tooltip; click a month to select it.
5. **Spending by category vs limit** — per-category progress bars:
   - grey track = the limit; fill = spent
   - **green** while under limit with "₹X left"; **red** when over with "₹X over"
     and a tick marking where the limit was
   - "No limit set" categories shown in muted grey
   - sorted by % of limit used (desc); summary line: "₹spent of ₹limits in limits, ₹left left · N categories over"
   - click a category → filters the transaction list to it
6. **Income by source**: horizontal bars with a thin line for the previous month.
7. **By account** table: Account · Income · Spending · Invested · Net (transfers excluded).
8. **Transactions** table for the selected month:
   - filters: free-text search, **Account dropdown**, **Category dropdown**,
     "Needs review only" toggle, "Clear filters"
   - filters persist when the month changes
   - sortable columns: Date, Description, Account, Category, Type, Amount
   - needs-review rows marked with a yellow left edge; transfers muted; income amounts green
   - from here, inline re-categorise (opens the same flow as the review queue)

Small fixes vs the mockup: compact axis labels should read `₹50K / ₹1L / ₹1.5L`
(the mockup shows "₹50T"); over-limit text should read "₹94 over" (no minus sign).
Must work in light and dark mode and down to ~400 px wide.

**Metric definitions** (put these in code as the single source of truth and in the UI as tooltips):
- Income = Σ `income`; Spending = Σ `expense`; Invested = Σ `investment`; transfers excluded.
- Net saving = Income − Spending. Savings rate = Net saving ÷ Income.
- Account net = Income − Spending − Invested for that account.
- Budget remaining = Limit − Spent for that category and month.
- Months are calendar months by transaction date (not statement period).

### 4.8 Settings page
Sections (tabs):
- **Accounts** — CRUD, link each to a parser, keychain password on/off.
- **Categories** — CRUD, type, colour, parent; merge two categories.
- **Rules** — list with search, priority drag-reorder, test a rule against existing
  transactions ("would match 14 transactions") before saving, enable/disable, import/export.
- **Budgets** — monthly limit per category.
- **Parsers** — installed parsers with name, version, supported banks; enable/disable;
  per-parser options (e.g. date format hints).
- **Import history** — past imports, row counts, roll back.
- **Data** — data dir location, backup (copy SQLite + optional PDFs to a zip), restore,
  export transactions CSV, "delete all data".
- **Preferences** — currency/locale (INR/en-IN default), first day of month (calendar month in v1), theme.

---

## 5. Suggested domain model (starting point — refine in the architecture)

- `Account(id, name, institution, type, masked_number, parser_id, currency, active, created_at)`
- `Import(id, account_id, file_name, file_sha256, parser_id, parser_version, period_start, period_end,
  opening_balance, closing_balance, reconciled bool, rows_parsed, rows_inserted, rows_skipped, created_at)`
- `Transaction(id, account_id, import_id, date, value_date?, description_raw, description_norm,
  amount (positive, Decimal), direction (debit|credit), balance_after?, category_id, type,
  categorised_by (rule|manual|default), rule_id?, needs_review bool, fingerprint UNIQUE, notes?)`
- `Category(id, name, type, parent_id?, colour, is_system)`
- `Rule(id, priority, match_kind, pattern, account_id?, direction?, amount_min?, amount_max?,
  category_id, label?, enabled, created_at, hits)`
- `Budget(id, category_id, monthly_limit, effective_from_month)`
- `Setting(key, value)`

Money: use `Decimal` in Python and integer paise or decimal strings over the API —
**never floats** for stored amounts.

---

## 6. Parser plugin contract (sketch)

```python
class StatementParser(Protocol):
    id: str            # "hdfc_savings_pdf"
    name: str          # "HDFC Bank — savings account (PDF)"
    version: str       # bump when output changes
    file_types: tuple[str, ...]  # (".pdf",)

    def detect(self, doc: OpenedDocument) -> float: ...        # 0.0–1.0 confidence
    def parse(self, doc: OpenedDocument) -> ParsedStatement: ...

@dataclass
class ParsedStatement:
    institution: str
    account_hint: str | None      # masked number / last 4
    period_start: date | None
    period_end: date | None
    opening_balance: Decimal | None
    closing_balance: Decimal | None
    transactions: list[ParsedTransaction]
    warnings: list[str]

@dataclass
class ParsedTransaction:
    date: date
    value_date: date | None
    description: str
    amount: Decimal               # positive
    direction: Literal["debit", "credit"]
    balance_after: Decimal | None
    raw: dict                     # original cells, for debugging
```

- `OpenedDocument` wraps the decrypted PDF (pdfplumber pages, extracted text and
  tables) so parsers don't each re-open or decrypt it.
- **Discovery:** built-in parsers in `parsers/` plus third-party ones via Python
  entry points (group `finboard.parsers`).
- Parsers are **pure** (no DB, no network) → easy to unit-test.
- **Each parser ships with tests that use a synthetic PDF generated by a fixture
  builder** (e.g. reportlab) reproducing that bank's layout with fake data.
  A shared test asserts every parser's output reconciles (opening + credits − debits = closing).
- A `CONTRIBUTING.md` section: "How to add your bank" (generate a fake fixture,
  write `detect` + `parse`, run the contract tests). Never attach real statements to issues.

Likely future inputs via the same contract: bank CSV/XLS exports, credit card
statements, and the **CAMS/KFintech Consolidated Account Statement (CAS) PDF**
for mutual-fund holdings (holdings/valuation is a v2 feature).

---

## 7. Non-functional requirements

- **Security:** bind `127.0.0.1`; reject non-local `Host` headers; CORS only for the dev
  frontend origin; uploaded files size-limited and parsed in-process with timeouts;
  no `eval`/pickle on user data; passwords only in memory or the OS keychain.
- **Run experience:** one command after clone (e.g. `uv run finboard` or `make dev`).
  In production mode FastAPI serves the built React app on one port and opens the browser.
- **Cross-platform:** Linux, macOS, Windows.
- **Quality:** pytest (unit + API), Vitest (components), Playwright (one happy-path import → dashboard);
  ruff + mypy (strict on core), ESLint + Prettier; GitHub Actions CI on all three OSes.
- **Performance:** comfortable with ~50k transactions; dashboard API < 200 ms locally.
- **Migrations:** Alembic from day one.
- **Accessibility:** keyboard navigable, sortable headers expose `aria-sort`, colour is never the only signal (text says "over"/"left").

---

## 8. Out of scope for v1

AI/LLM categorisation · multi-user/auth · cloud hosting or sync · mobile app ·
automatic email fetching (planned later as a **separate Go tool** that pulls statement PDFs
via IMAP into an import folder — keep an "import folder watcher" in mind as an extension point) ·
investment valuation/NAV tracking · multi-currency.

---

## 9. Phased plan (proposal — architecture phase may revise)

0. **Architecture** (this handover's first task) — docs only, then stop for review.
1. Skeleton: repo layout, backend + frontend dev servers, SQLite + Alembic, CI, settings for accounts/categories.
2. Import pipeline: upload, decrypt, parser registry, `generic_table` parser, preview, dedupe, commit, rollback.
3. Categorisation: rules engine, review queue, rule-from-review, re-apply.
4. Dashboard + transactions page (match `design/`).
5. Budgets + settings polish, backup/restore.
6. First real bank parser(s) once the owner names the banks (with synthetic fixtures).
7. Packaging: production single-port run, Docker image, release notes.

---

## 10. Open questions for Kapil

1. Which banks are the savings accounts and credit card with? (Decides the first parsers.)
2. Mutual funds: one "Investments" category, or a sub-category per fund?
3. Do statements arrive as text PDFs (selectable text) or scanned images? (OCR is out of scope unless needed.)
4. Should refunds count as income or reduce spending in the original category?
5. Keep archived copies of imported PDFs in the data dir — yes/no by default?

---

## 11. Files in this handover

```
finboard-handover/
├── HANDOVER.md               ← this file (requirements + decisions)
├── KICKOFF_PROMPT.md         ← paste into Claude Code first
└── design/
    ├── dashboard-mockup.html ← approved dashboard, runs offline from sample CSVs
    ├── dashboard-mockup.png  ← screenshot of the above
    ├── sample-transactions.csv ← made-up data (Jul–Sep 2026), shows the data shape
    └── budgets.csv           ← made-up monthly limits per category
```
