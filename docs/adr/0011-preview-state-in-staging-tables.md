# ADR-0011: Preview state stored in database staging tables

**Status:** Accepted (revised 2026-10-18: Postgres + BlobStore)

**Options.** (a) In-memory dict with TTL. (b) Redis. (c) `import_batch` + `staged_row` tables.

**Decision.** (c). Upload creates an `import_batch`. The parse job writes `staged_row`s with fingerprint, duplicate flag and proposed category. The original, still-encrypted file lives in the BlobStore ([ADR-0026](0026-blob-storage.md)) so the user can re-parse with a different adapter or account. Commit is one SQL transaction. Staged imports expire after 7 days (beat task).

**Why.** (a) breaks with several API instances and with restarts. (b) is meant to be disposable. Database staging survives restarts, works across stateless API and worker processes, makes row edits ordinary updates, and lets a future folder watcher create imports while no UI is open.

**Consequences.** Staged rows are as sensitive as committed ones and get the same RLS and isolation.
