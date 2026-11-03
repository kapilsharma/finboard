# ADR-0028: UUIDv7 primary keys

**Status:** Accepted

**Decision.** All primary keys are `UUID DEFAULT uuidv7()` (native in PostgreSQL 18).

**Why.** Ids are not enumerable or guessable across tenants, can be generated anywhere when needed, and are time-ordered, so B-tree inserts stay append-friendly, unlike random UUIDv4. `(date, id)` gives a stable keyset-pagination order.

**Cost.** 16 bytes vs 8, and less readable in logs. Both are acceptable.
