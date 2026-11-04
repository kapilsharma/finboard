# ADR-0030: Assistive AI, opt-in, behind a strict privacy boundary

**Status:** Accepted (owner decision 2026-11-04; revised the same day after review). Amends [ADR-0005](0005-no-ai-deterministic-rules.md) and HANDOVER §2 / §8 ("no AI in v1").

**Context.** Finboard is also the owner's open-source portfolio project for Python + AI developer roles. Its learning goals now include LLM application work: LangChain, LangGraph, structured output, embeddings and vector search, and LLM evaluation. A separate RAG demo ("Ask Your Docs") was considered and set aside: Finboard is a real product with real engineering (RLS, jobs, CI, ADRs), so AI features built into it make a stronger, more distinctive project. The constraints are a 5-year-old 16 GB laptop (no large local models) and a zero budget. The Gemini API free tier covers the Flash models and needs no card (the owner checked this on 2026-11-04). On the free tier, Google may use submitted content to improve its products, which can include human review. The privacy promise still holds: **statement data stays on the machine.**

**Decision.**
1. **Rules stay authoritative.** AI only suggests. It never categorises a transaction without a user action. Every auto-categorised transaction still has a `rule_id`. Accepting a suggestion counts as a manual categorisation (`categorised_by=manual`), or the user turns it into a rule through the existing rule suggester.
2. **Two features, both off by default, with two levels of switch.** The operator decides whether a feature is *available* on this server (environment). Each user decides whether to *use* it (Settings › AI, stored in `user_setting`, default off). This follows the multi-user design ([ADR-0021](0021-multi-user-ready-single-user-first.md)).

   | Feature | Operator switch (availability) | Per-user opt-in |
   |---|---|---|
   | **Category suggestions**: embeddings of normalised descriptions, nearest neighbours among the user's own categorised transactions. **Fully local**, no network ([ADR-0031](0031-pgvector-embeddings.md)) | `FINBOARD_AI_SUGGESTIONS=on\|off` | `ai.suggestions` |
   | **Ask Finboard**: plain-English questions answered as a chart or table, which can be pinned to the dashboard ([ADR-0032](0032-nl-analytics-langgraph.md)) | `FINBOARD_AI_ASK=off\|gemini\|ollama` | `ai.ask` |

3. **Privacy boundary for a hosted LLM.** A request may contain only:
   - the user's question text
   - the query catalog: view names, column names and their descriptions
   - the user's category paths
   - **account aliases**, never account display names (`Account A — savings, ICICI Bank`), mapped back to real accounts locally
   - on a retry, a **locally generated** error description: the guard's rejection reason, or an error class plus identifiers that appear in the model's own SQL. The database's own error text is never forwarded, because it can quote data values (for example, a failed cast prints the value).

   A request **never** contains transaction rows, descriptions, amounts, balances, account numbers, account display names or query results. Answer text is built locally from the results with templates.
4. **One outbound path, and nothing else.**
   - `finboard.ai.llm` is the only code allowed to call an LLM provider. Its payload is built from a typed, allow-listed request model. A canary test fails if any value from the synthetic dataset appears in a request.
   - **Tracing is forced off.** At startup, `finboard.ai` overrides `LANGSMITH_TRACING` and `LANGCHAIN_TRACING_V2` to `false` and clears the LangSmith endpoint and key variables. A test fails if tracing can be switched on through the environment.
   - **Query results never enter the LangGraph state.** They are kept in a local per-request store, and the graph carries only a result id plus a shape summary (column names and types, row count). So even a mis-configured callback or tracer has no data to send.
5. **Provider-agnostic.** The code uses LangChain's chat-model interface. The default is a **Gemini Flash** model (exact id in config: `FINBOARD_AI_MODEL`, key in `FINBOARD_GEMINI_API_KEY`). Ollama with a small local model is an optional offline fallback.
6. **Optional install.** AI libraries live in an `ai` extra (`uv sync --extra ai`). `services/ai.py` imports them lazily, so the core install stays lean and the app starts without them; the features then report as unavailable.

**Why each boundary rule exists** (security review, 2026-11-04). Each rule closes a specific path by which statement data could leave the machine, or one user's data could reach another.

| Rule | Leak it prevents | Alternative considered, and why not |
|---|---|---|
| Rows never sent; answers from local templates | The obvious one: transactions, amounts and balances at the provider, and on the free tier possibly used for training or read by reviewers | Letting the LLM write the answer from aggregates (nicer prose): rejected for v1 (OQ-33); aggregates still reveal income and spending patterns |
| Account **aliases**, not display names | Users name accounts freely ("Salary — Acme Corp", "HDFC 4321"), so names can carry an employer or account digits. The model needs the account's *type and bank* to map "my credit card", not its name | Sending names: rejected; sending nothing: rejected, because the model then can't resolve "ICICI card" questions |
| Retry messages generated locally | Database error text can quote **data values**: a failed cast prints the offending value (e.g. a merchant description). Truncating the message doesn't help, because the value is near the start | Forwarding the raw error (common in text-to-SQL demos): rejected; SQLSTATE only: too little for the model to fix its query |
| One outbound module + canary test | A second, forgotten call site (a helper, a library default) quietly sending data. The canary turns "we never send X" into a test that fails | Code review alone: rejected; it doesn't scale and doesn't catch library behaviour |
| Tracing forced off | LangChain/LangGraph auto-enable LangSmith tracing from environment variables, and a trace contains prompts *and graph state*. An inherited env var would ship everything to a third party, bypassing the one-module rule | Documenting "don't set those variables": rejected; it fails silently |
| Rows kept out of graph state | Defence in depth for the rule above: even a mis-configured tracer or callback has no rows to send, because the graph only holds a result id and a shape summary | Trusting the tracing switch alone: rejected; one control for one leak is too thin |
| Operator availability + per-user opt-in | On a shared server (ADR-0021), one operator switch would send *every* user's questions to a provider without their consent | Env switch only: rejected; per-user only: rejected, because the operator must be able to keep a provider off entirely |
| Embedding model fetched explicitly | A silent first-run download would be an unannounced network call, breaking "nothing calls out" | Lazy download on first use: rejected |

**Consequences.** The README's "nothing calls out to the internet" becomes "nothing calls out unless you turn on Ask." The question text itself goes to the provider, so the UI says so next to the input box, including that the free tier may use it to improve Google's products. Free-tier rate limits cause HTTP 429 errors, which the app shows as a friendly "try again shortly." The embedding model is downloaded once, by an explicit `finboard ai fetch-model` or at Docker image build time, never silently at runtime. Unit tests keep blocking the network. LLM tests use recorded responses, and a live evaluation is a manual command.
