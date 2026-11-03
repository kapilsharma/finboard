# ADR-0017: Metrics use signed sums per type (refunds reduce spending)

**Status:** Accepted (owner, 2026-10-18: refunds go to the original category)

**Context.** HANDOVER defines Spending = Σ expense, which assumes every expense is a debit. Refunds, cashback and reversals arrive as credits.

**Decision.** For each type, metrics use a signed sum: Spending = Σ expense debits − Σ expense credits. Income = credits − debits. Invested = debits − credits. A refund categorised into *Shopping* reduces Shopping (and its budget usage). The seeded **Refunds** income category stays available for users who prefer refunds counted as income. This is purely a categorisation choice, and the maths stays the same.

**Consequences.** A category's spent amount can be negative in a month where refunds exceed purchases. The UI shows it as "₹X refunded". Investment redemptions reduce Invested, which is a sensible v1 behaviour before holdings tracking exists.
