# ADR-0020: Regex rules via the `regex` package with a timeout

**Status:** Accepted

**Context.** Rule packs are shareable, so a pasted pattern can be catastrophic (ReDoS). The stdlib `re` has no timeout.

**Decision.** `match_kind=regex` uses the `regex` package (well-maintained, near drop-in for `re`) with `IGNORECASE` and `timeout=0.05` s per evaluation. Patterns are compiled on save and rejected if longer than 500 characters. A timeout during matching disables the rule and flags it in Settings › Rules. `contains`, `starts_with` and `equals` use plain string operations.
