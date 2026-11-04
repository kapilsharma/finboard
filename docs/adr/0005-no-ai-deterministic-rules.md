# ADR-0005: No AI in v1 — deterministic, explainable categorisation

**Status:** Accepted (given — HANDOVER §2, §4.5). **Amended by [ADR-0030](0030-assistive-ai-opt-in.md)** (2026-11-04): rules stay the only thing that auto-categorises, but optional AI may *suggest* categories (locally) and answer questions.

**Decision.** Categorisation uses only the description (plus optional account/direction/amount constraints) and user-editable rules, with first match by priority. Every auto-categorised transaction stores `rule_id`.

**Consequences.** Predictable and testable, and no data leaves the machine. More manual review up front, which the rule-from-review suggester and starter rule pack offset.
