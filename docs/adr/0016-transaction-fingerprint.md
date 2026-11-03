# ADR-0016: Transaction fingerprint for idempotent imports

**Status:** Accepted (implements HANDOVER §4.2)

**Decision.**

```
sha256("v1|account_id|date|direction|amount (2 dp)|dedupe_desc|balance_after (2 dp) or ''|seq_in_day")
dedupe_desc = upper(collapse_ws(NFKC(description_raw)))     # frozen; reference numbers kept
seq_in_day  = occurrence index of an identical preceding tuple within the same statement
```

The fingerprint is stored in `txn.fingerprint` with `UNIQUE (user_id, fingerprint)` and `fingerprint_version`. Commit inserts with `ON CONFLICT DO NOTHING`, so concurrent imports can't create duplicates. `import_row` records every fingerprint an import saw, so a rollback of overlapping statements reassigns rows instead of deleting them.

**Why a separate `dedupe_desc`.** The categorisation normaliser must be free to evolve, and changing it must never create duplicates. Reference numbers help uniqueness rather than hurting it.

**Known limits.**
- If a bank renders the same description differently in two statements (e.g. truncation), the row is duplicated. Mitigation: the preview flags "possible duplicates" (same account, date, amount and direction but different text) for the user to exclude.
- A statement boundary that splits a day containing identical rows can shift `seq_in_day`. `balance_after`, when present, disambiguates. Rare and accepted.
