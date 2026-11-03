# ADR-0005: No AI in v1 — deterministic, explainable categorisation

**Status:** Accepted (given — HANDOVER §2, §4.5)

**Decision.** Categorisation uses only the description (plus optional account/direction/amount constraints) and user-editable rules, with first match by priority. Every auto-categorised transaction stores `rule_id`.

**Consequences.** Predictable and testable, and no data leaves the machine. More manual review up front, which the rule-from-review suggester and starter rule pack offset.
