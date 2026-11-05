# ADR-0038: Category suggestions as built (M3a)

**Status:** Accepted (2026-11-05, M3a / issue #6). Refines [ADR-0030](0030-assistive-ai-opt-in.md), [ADR-0031](0031-pgvector-embeddings.md) and ARCHITECTURE §18.

**Context.** M3a adds local category suggestions: embeddings of transaction descriptions, nearest neighbours among the user's own categorised transactions, a weighted vote. Building and evaluating it settled several details, and checking it in the real app turned up a calibration problem that the first evaluation could not see.

**Decisions.**

1. **What gets embedded: the merchant words only** (`ai/text.py`).
   - Bank narrations share a lot of format text (`UPI DR … YESB … @ybl PAYMENT`). Left in, it makes unrelated merchants look alike, and no similarity cut-off can separate "the same merchant" from "the same bank's format".
   - `match_text()` reuses the rule suggester's `merchant_tokens` (channels, markers and numbers dropped) and also drops bank codes, UPI handles and payment filler. A description with no merchant words left gets no suggestion.
   - Stored vectors are keyed `"<model>#text<N>"`, so changing the text rules (or the model) rebuilds them through `ai.embed_all`.
   - Effect on held-out top-1 accuracy: all-MiniLM-L6-v2 went from 0.832 to **0.948** (trigram baseline 0.764).
2. **The evaluation includes merchants the user never categorised.**
   - The first version only had queries for merchants with labelled examples, so it could not tell how high the "too different to vote" cut-off should be. The guessed value (0.5 cosine) hid an obvious match in the demo data ("UPI SWIGGY INSTAMART" vs a categorised "SWIGGY / ZOMATO", 0.36).
   - 16 never-categorised merchants are now part of every seed. Each method's cut-off is tuned on seed 7 for utility (+1 right suggestion, −1 wrong one, −1 any suggestion for an unseen merchant, 0 none) and reported on the four held-out seeds.
   - The served values (sharpness 3 and cut-off 0.45 for embeddings, sharpness 3 and no cut-off for trigram) are the evaluation's. Unit tests fail if code and evaluation disagree.
3. **The default model stays all-MiniLM-L6-v2.** BAAI/bge-small-en-v1.5 scores 0.953 against MiniLM's 0.948, within seed-to-seed noise. On real-format demo descriptions neither model is consistently better. The report says this itself (`NOISE = 0.01`).
4. **The baseline is pg_trgm trigram similarity**, not a character n-gram TF-IDF or `rapidfuzz`.
   - It is also the production fallback: "auto" uses the embedding when the transaction has one, else trigram.
   - `ai/trigram.py` is an exact Python twin of `similarity()`, and a test checks them against each other, so the offline evaluation measures what the database runs. No new dependency.
5. **The API never loads the model.** The query vector is the transaction's own stored embedding. A transaction is embedded after its import commits (`ai.embed`). Turning suggestions on embeds everything not yet embedded (`ai.embed_all`).
6. **pgvector setup.**
   - **Image:** `pgvector/pgvector:pg18-trixie`, not `pg18`. The `pg18` tag is built on Debian bookworm, and an existing trixie volume then reports a collation version mismatch.
   - **Extension:** `vector` isn't a trusted extension, so the migration (run as `finboard_owner`) can't create it. `deploy/postgres/init/01-finboard.sh` creates it on new volumes, and `scripts/enable-pgvector.sh` adds it to an existing database. The migration checks for it and stops with that instruction.
   - **Column type:** our own small `Vector` type (`db/vector.py`) instead of the `pgvector` Python package, so the core install needs nothing new. It is registered for Alembic reflection.
7. **Data handling.**
   - Delete-all removes `ask_query` and `dashboard_widget`. Embeddings go with their transactions through `ON DELETE CASCADE`.
   - The export leaves out the AI tables, contrary to ADR-0031's note. Embeddings are derived and rebuilt on demand, and the Ask history is a log of questions, not financial data.
8. **UI.** Suggestions show in the categorise dialog, which the review groups and the transaction table open, with **Accept** (a manual categorisation) and **Make a rule** (the M3 rule editor, category filled in). They are not shown inline in the review groups.
9. **Tests.**
   - Unit tests allow Unix sockets (an asyncio event loop needs a local socketpair). Network sockets stay blocked, and a test checks that.
   - Integration tests use a deterministic stand-in embedder. The real-model verdict test runs whenever the model is on disk.

**Measured.** 5,000 transactions embedded in 6.5 s through the real `ai.embed_all` task, with a peak RSS of 454 MB for the whole test process (budget: 60 s, 600 MB).

**Consequences.** The suggestion evaluation is now a calibration tool: re-run `finboard ai eval-suggestions` after changing the model, the text rules or the vote. If a unit test then fails, copy the reported sharpness and cut-off into `ai/suggest.py` and `services/ai.py`. The synthetic data still decides the cut-off. Real statements may need a different one, which the owner can check once suggestions run on real data.
