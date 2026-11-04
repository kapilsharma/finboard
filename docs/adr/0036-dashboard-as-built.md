# ADR-0036: Dashboard and transactions as built (M4)

**Status:** Accepted (2026-11-04, M4 / issue #4). Refines ARCHITECTURE §10–§12 and §14, and [ADR-0012](0012-charts-d3-react-svg.md).

**Context.** The approved mockup (`docs/handover/design/dashboard-mockup.png`) and ARCHITECTURE §12 disagree in one place, and building M4 settled several details the specification leaves open.

**Decisions.**

1. **Limits summary: left = Σ limit − Σ spent** over the categories that have a limit, which is negative when over in total. This is what the approved mockup shows: "₹89,190 spent of ₹95,000 in limits, ₹5,810 left · 2 categories over". §12 said Σ max(remaining, 0), which would show ₹6,172 left while two categories are over, hiding the overspend. The approved design wins, and §12 is updated.
2. **Percentages are rounded once, to one place, half up, in `domain/metrics.py`.** The API sends what the UI shows (32.7, −10.2). Rounding to two places and then to one in the browser turned −11.2504 % into −11.2 %, where the mockup shows −11.3 %. Money stays exact (decimal strings); the browser rounds whole rupees by string arithmetic.
3. **Δ % against a negative previous month** divides by the absolute value, so going from −₹100 to +₹100 reads as +200 %, not −200 %.
4. **The empty state.** `GET /dashboard` returns `null` when the user has no transactions. Without `month`, it shows the latest month with data. A month after the data shows zeros, with the limits still listed.
5. **Category limits list** includes every expense category with spending or a limit in force. Sub-categories are listed separately; rolling them into their parent is M5 work, together with the Budgets UI. Budgets can only be set on expense categories.
6. **The ETag** is weak and derived from `(user_id, data_version, month, trail)`. `data_version` is now bumped by category and account edits and by budget changes too, because names and limits show on the dashboard.
7. **`/transactions`** keyset-pages on `(sort value, id)` for every sort column. `q` matches the raw description, the account name and the category name; it also matches the normalised description, which uses the trigram index. A category filter includes its sub-categories. `total` and `sums` cover every matching row, not just the page.
8. **Test locations.**
   - The golden test, the dashboard perf test and the ETag test live under `tests/integration/` (`golden/`, `perf/`, `test_etag.py`), so they can use the database fixtures.
   - The e2e tests run against `finboard serve` with the demo data, which `e2e/stack.py` loads after emptying `finboard_test`. The M7 compose stack takes over then.
   - The demo CSVs ship inside the package (`finboard/seed/demo/`), and a test keeps them identical to the handover copies.
9. **API processes.** `finboard serve --workers N` runs N stateless API processes (§14). Under the Locust mix with 200 virtual users on a 4-CPU sandbox:
   - one process saturates at about 130 requests/s, and p95 reaches 930 ms;
   - three processes give p95 57 ms overall (dashboard 59 ms, transactions 51 ms), inside the 300 ms budget.

   The default stays 1 for the single-user local app; M7's compose file should set it.
10. **Libraries.** `d3-scale` is v4, the current major (§11 said v3). The API it uses is the same.

**Consequences.** The limits summary can now read "₹X over" in total, which the mockup's wording already supports. Load results depend on the number of API processes, so the M7 packaging must set it.
