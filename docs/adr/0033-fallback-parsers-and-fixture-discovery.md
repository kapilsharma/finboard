# ADR-0033: Fallback parsers, and fixture builders discovered through entry points

**Status:** Accepted (2026-11-04, M2 / issue #2). Refines [ADR-0009](0009-parser-discovery-entry-points.md) and ARCHITECTURE §8.

**Context.** M2 ships a generic adapter, `generic_table`, that reads any statement laid out as one transaction table. By design it recognises many files, including the ones bank-specific adapters are written for. Under the §8 rule ("the top score ≥ 0.5 wins; within 0.1 the user chooses"), a confident generic match would compete with, or be confused with, the right bank adapter. That makes detection depend on how carefully each adapter tunes its score against a parser it doesn't know about.

Separately, the contract suite has to find every adapter's synthetic fixture builder. ARCHITECTURE §8 says each adapter "ships `fixtures.py`", but not how the suite finds it. Importing `<package>.fixtures` by convention only works for built-ins, while third-party adapters live in their own distributions.

**Decision.**
1. **`fallback` attribute.** A parser may set `fallback = True` (optional; default `False`, read with `getattr`, so `PARSER_API_VERSION` stays 1). Detection keeps every candidate's score, then chooses:
   - the best **specific** parser at or above 0.5, if any;
   - otherwise the best **fallback** at or above 0.5;
   - otherwise nothing ("No parser recognised this file", with the candidates listed).

   Only specific parsers count towards the "top two within 0.1 → ambiguous" check. Fallbacks are listed after specific parsers in Settings › Parsers and in the candidate list. `generic_table` is the only fallback today.
2. **Contract suite and fallbacks.** The detect matrix ("other parsers score < 0.5 on my fixture") applies only to specific parsers. A fallback may match anything; the ranking above keeps it from winning. The suite still checks that the registry picks the owning adapter for every fixture.
3. **Fixture builders are discovered through a second entry-point group, `finboard.parser_fixtures`**, keyed by parser id. The builder's `parser_id` must equal the parser's `id`. The contract suite fails for a registered parser with no builder. Builders are test-only code, but they ship in the package so a third-party adapter is tested exactly like a built-in.
4. The contributor `_template` adapter is **not** registered, so it never appears in a user's parser list. The contract suite adds it explicitly, so it can't rot.

**Why.** Bank adapters stay simple: they only need to beat other *bank* adapters, never the generic one. The user gets the specific adapter whenever one exists, and the generic one as a safety net. The entry-point group reuses the mechanism from ADR-0009, so one path covers built-in and out-of-tree adapters, and adding a bank never means editing the test suite.

**Alternatives rejected.**
- Giving `generic_table` a fixed low score (e.g. 0.5 at most): it then ties with weak specific matches and triggers "ambiguous" prompts, and its confidence stops meaning anything.
- A score penalty for fallbacks: the same problem in a different place, and it still needs tuning.
- Finding fixtures by module naming convention (`<parser module>.fixtures`): doesn't work for third-party packages laid out differently, and fails silently when a file is missing.
- A registry of builders inside `tests/`: every new adapter would need a test-suite edit, and out-of-tree adapters couldn't use it.
