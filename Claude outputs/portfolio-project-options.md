# Portfolio Project Options: Context for Deciding

*Summary of an earlier discussion, written on 2026-11-04. Use it alongside the Finboard docs to choose which project to build.*

## My goals and constraints

- **Goal:** an open-source GitHub portfolio project for job searching as a **Python + AI developer**.
- **Learning targets:** FastAPI, data engineering, AI/LLM features, **LangChain, LangGraph** and similar popular tools.
- **Hardware:** a 5-year-old laptop with 16 GB RAM. Avoid anything that needs large local models or heavy infrastructure.
- **LLM access:** prefer hosted models (Gemini, OpenAI, Claude) over local models, and use free tiers where possible.
- **Background:** professional PHP developer moving into the Python/AI space.

---

## Option A: "Ask Your Docs" (RAG API with citations)

Upload PDFs or Markdown files, ask questions, and get answers that cite their sources.

### Skills it shows
| Area | What it covers |
|---|---|
| FastAPI | File upload, async endpoints, background ingestion jobs, Pydantic models, dependency injection, OpenAPI docs |
| Data engineering | Parse → clean → chunk → embed → index pipeline, metadata, idempotent re-ingestion |
| AI | Embeddings, vector search, prompt construction, citation checking, retrieval evaluation |
| LangGraph | Agentic RAG graph: retrieve → grade relevance → rewrite query if weak (loop back) → generate → check citations |

### Keeping it light
- Embeddings: `all-MiniLM-L6-v2` (about 90 MB, runs on CPU), or a hosted embedding API.
- Vector store: ChromaDB or FAISS locally, or Qdrant in Docker.
- Generation: a hosted LLM free tier (see below). Keep a small Ollama model (1–3B) as an offline fallback.
- Demo corpus: a few dozen documents.

### Milestones (about one weekend each)
1. **Core API:** `/health`, `/documents` upload, storage, Pydantic schemas, pytest.
2. **Ingestion pipeline:** a background task with a `/documents/{id}/status` endpoint.
3. **Query:** `/ask` returns an answer plus the source chunks it used.
4. **LangGraph upgrade:** relevance grading, a query-rewrite loop, and a citation check.
5. **Evaluation:** a test set of 20–30 questions, with a script that reports retrieval hit rate and latency and a results table in the README. Show whether the rewrite loop improves the hit rate.
6. **Polish:** Dockerfile, GitHub Actions CI (lint and tests), an architecture diagram, and a demo GIF.

### Why it stands out
Most portfolio RAG projects are a notebook with no metrics. **The evaluation script, measured results and CI are what set this one apart.**

### Weaknesses
- RAG demos are very common, so it needs the evaluation work and polish to stand out.
- It is a "toy" corpus with no real user, unlike a product I actually use.

---

## Option B: Finboard + natural-language analytics (see the Finboard docs)

Finboard is my private personal-finance app: React → FastAPI (async) → PostgreSQL with row-level security, plus Celery and Redis for PDF statement parsing. It has rule-based categorisation and a dashboard. M1 (the platform skeleton) is done. Its current stated principles are **"no AI"** for categorisation and **"nothing calls out to the internet."**

**Proposed enhancement:** ask questions like *"Give me a monthly breakdown of eating out and provisions for the last six months."* The system understands the question, builds a query, fetches the data, and shows a chart on the dashboard.

### Is it a good project, and does it use AI?
**Yes on both counts.** This is **text-to-SQL / natural-language analytics**, one of the most in-demand applied LLM patterns, and it uses LLMs in a real, practical way:

| AI feature | How it shows up |
|---|---|
| Intent and entity extraction | The question becomes {metric, categories, time range, grouping}. This uses LLM **structured output** with Pydantic schemas |
| Text-to-SQL | The LLM writes SQL against a documented schema or views |
| Tool calling / agents | A **LangGraph** graph: understand → plan → generate SQL → validate → execute → **on error, feed it back and retry (loop)** → pick a chart type → summarise |
| Chart selection | The LLM returns a chart spec (bar, line or table, plus axes) that the React dashboard renders |
| Optional: embeddings | Local embeddings over transaction descriptions to suggest categories ("similar to past Swiggy rows → Eating out"). This adds vector-search skills without sending data out |

### Engineering points that make it impressive (and safe)
- **Two query modes.** (1) A *semantic layer*: the LLM fills a typed query spec, and the code builds the SQL. This is safe and reliable. (2) *Free-form SQL* for open-ended questions. Comparing the two in the README is a good discussion point for interviews.
- **SQL guardrails:** a read-only DB role, the existing **RLS** (so queries can only see the user's own rows), parsing with `sqlglot` to allow a single `SELECT`, an allow-list of views, `statement_timeout`, and a forced `LIMIT`.
- **Evaluation:** a golden set of about 30 questions with expected results on **synthetic data**, measuring *execution accuracy* and retry rate per model. This is the metric that recruiters notice.
- **Model-agnostic config:** an environment variable chooses Gemini, OpenAI, Claude or local Ollama.

### The privacy tension (must be decided)
Finboard currently promises that nothing leaves the machine. Options:
1. **Send only the schema, the category names and the question to a hosted LLM, never transaction rows.** The query runs locally, and results are charted locally. The summary text is generated from aggregates only, or skipped.
2. **Local model only** (for example, a small coder model through Ollama). This is fully private but slower and less accurate on a 16 GB laptop.
3. **Make AI an opt-in feature flag that is off by default.** Update the README's "no AI" claim, and add an ADR documenting the decision.

### Weaknesses
- The AI feature needs data, so it depends on **M2 (import), M3 (categorisation) and M4 (dashboard)** being built first. That pushes the AI work later.
- The stack (Postgres, Redis, Celery, Vite and Docker) is heavier on the laptop, though it should be workable.
- On its own it covers text-to-SQL and agents but not RAG (unless the embeddings add-on is included).

---

## Side-by-side

| | A: Ask Your Docs | B: Finboard + NL analytics |
|---|---|---|
| Time to first AI feature | Fast (weekend 2–3) | Slow (after M2–M4) |
| AI skills covered | RAG, embeddings, vector DB, LangGraph, evals | Text-to-SQL, structured output, agents/tools, LangGraph, evals (plus optional embeddings) |
| Data engineering | Document ingestion pipeline | PDF parsing, reconciliation, dedupe, Postgres modelling (much deeper) |
| Uniqueness | Common, so it needs polish | Distinctive, a real product I use |
| Laptop load | Light | Moderate |
| Privacy concerns | None (public docs) | Real, so it needs a design decision |
| Interview story | "I built and evaluated a RAG system" | "I built a secure NL analytics layer on my own finance app" |

Possible middle path: build Finboard as the main project, and do a small "Ask Your Docs" repo as a quick RAG side project, or add RAG to Finboard later (for example, Q&A over bank terms and conditions or statement notes).

---

## LLM API free credits (researched 2026-11-03; check official pricing pages before relying on this)

- **Gemini (Google): the best free option.** A free API key from Google AI Studio needs no card. Since April 2026 the free tier covers **Flash and Flash-Lite models only** (Pro is paid), and rate limits were cut. Paid tiers have enforced monthly spend caps. Free-tier content **may be used to improve Google's products**, so don't send private data on the free tier.
- **OpenAI:** reports conflict on whether new accounts get small trial credits, so check the billing page. The student offer ($100) is for **Codex**, for US and Canada students only, not the general API.
- **Anthropic (Claude):** no reliable universal signup credit (some sites mention $5, so check the Console). Credits come mainly through programs (startups need a registered company; Claude Campus covers participating universities). A Claude Pro subscription does **not** include API credits.

**Plan:** build on the Gemini free tier with LangChain and LangGraph (both have Gemini integrations). Keep the provider swappable through config, set a spend cap on any paid account, keep evaluation sets small, and keep a small local model as a fallback.

---

## Repo tips (either option)
- README: a one-paragraph problem statement, an architecture diagram, a quickstart in under five commands, and evaluation results.
- Small, readable commits. Recruiters look at history.
- `.env.example`, and never commit keys (or, for Finboard, real statements).

## Question for the next chat
Which option (A, B or the hybrid) best fits my goals, and if B, which privacy approach (1, 2 or 3) and where should the AI milestone go in the Finboard roadmap?
