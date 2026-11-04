# ADR-0035: Categorisation as built (M3)

**Status:** Accepted (2026-11-04, M3 / issue #3). Refines ARCHITECTURE §5, §9 and §10, [ADR-0005](0005-no-ai-deterministic-rules.md) and [ADR-0020](0020-regex-rules-with-timeout.md).

**Context.** ARCHITECTURE §9 describes the categorisation engine in outline. Building it raised questions the outline doesn't answer, and in one case (the rule suggester) real-looking data showed the outline was wrong.

**Decisions.**

1. **The suggester proposes the first merchant token, not the longest.** Narrations put the merchant first and a city or description after it: "RELIANCE FRESH BANGALORE IN" should give `RELIANCE`, not `BANGALORE`, and "HPCL PETROL PUMP" should give `HPCL`. Generic words (REFUND, RECEIVED, ORDER, ONL, VPS, …) join the channel stop-words, so "IMPS/…/REFUND/APOLLO PHARMACY" gives `APOLLO`. The suggested token also groups the review queue.
2. **Rules run three times on an import.**
   - At parse time, on the staged rows. A row a rule matches shows its proposed category in the preview. An unmatched row has no category (`category_id` NULL) and counts as "needs review".
   - At commit, afresh, because rules may have changed since the preview. Categories the user chose by hand in the preview are kept.
   - On re-apply (`rules.apply`).

   `rule.hits` and `last_hit_at` count the transactions a rule categorises at commit and on re-apply.
3. **Re-apply** keeps the §9 provenance rules, with two refinements:
   - a `manual` row (with `include_manual`) only gives way to a rule that matches now, never to the fallback category;
   - a `rule` row whose rule no longer matches goes back to the fallback category and `needs_review`.

   Every run also rewrites `description_norm` wherever the normaliser now produces something different. That covers rows committed in M2, which stored the dedupe form.
4. **Fallback categories.** Unmatched debits go to *Uncategorized* and unmatched credits to *Uncategorized income*, both with `needs_review` (OQ-18). Rows in `loan`, `insurance` and `mutual_fund` accounts go to *Account movement* without review (OQ-25).
5. **Regex timeouts** (ADR-0020). The rule is skipped for the rest of the run, then `enabled=false` and `rule.error` records the reason, shown in Settings › Rules. Saving a changed pattern, or switching the rule back on, clears the error.
6. **Deleting a rule** keeps the categories it gave: `txn.rule_id` is set to NULL (`ON DELETE SET NULL (rule_id)`), and `categorised_by` stays `rule`, so the next re-apply with scope `all` re-evaluates those rows. A category used by any rule can't be deleted (409), like a category used by transactions.
7. **Transfer pairs.**
   - **Uniqueness.** `transfer_pair` doesn't have the plain `UNIQUE(debit_txn_id)` / `UNIQUE(credit_txn_id)` from §5. Rejected pairs are kept so they are never suggested again, so a transaction can appear in several rejected pairs. Instead, partial unique indexes allow at most one *suggested or confirmed* pair per transaction, and `UNIQUE(user_id, debit_txn_id, credit_txn_id)` stops the same pair being stored twice.
   - **Undoing a pair.** `DELETE /transfers/{id}` doesn't delete the row. It marks the pair rejected, so it isn't suggested again, and the rules categorise both sides afresh.
   - **Changing one side by hand.** Recategorising one side of a confirmed pair (`PATCH /transactions/{id}` or bulk) undoes the pair the same way, so the other side isn't left looking like half a transfer.
   - **When pairing runs.** `transfers.suggest` is queued after every commit that inserted rows, and on request (`POST /transfers/suggest`).
8. **Starter rule pack.** New users get it at provisioning (`seed/rules.py`). Existing users, including the owner's local user created in M1, can merge it with `POST /rules/starter-pack` or the "Add starter rules" button. A migration can't add it, because row-level security hides every user's rows from the migration role.
9. **Rule packs.**
   - **Format.** `finboard_rule_pack: 1`. Categories are referenced by path (`Parent / Child`) together with their type, and missing categories are created on import. Amounts are decimal strings; floats are refused. Account constraints are left out on export, and an `account_id` key in an imported pack is rejected.
   - **Modes.** `merge` (the default) appends the pack's rules and skips exact duplicates. `replace` swaps the user's rules for the pack's.
   - **Limits.** Packs are capped at 1 MB and 2000 rules.
10. **Performance.** Re-apply loads the scanned columns without building ORM objects, compiles each rule into one predicate, and writes changes with one `UPDATE … FROM unnest(arrays)` per 5000 rows. 50k transactions × 200 rules takes about 5 s in a worker here, against the 10 s budget. The perf test sits in `tests/integration/perf/` (not `tests/perf/`) so it can use the integration fixtures.

**Consequences.** The suggester is a heuristic, and users edit the pattern before saving. The live "would match N" count makes a bad pattern visible. Rows committed before M3 keep the old `description_norm` until the first re-apply. Rules still match correctly in the meantime, because re-apply and `/rules/test` normalise the raw text themselves.

**Alternatives rejected.**
- The longest token (§9 as first written): it picks cities and generic words, as above.
- A beat job to sweep rule hits or pairs: everything runs at commit or on request, so there is nothing to sweep.
- Deleting rejected pairs: "rejected pairs are never suggested again" needs them kept.
