# ADR-0012: Charts with d3 maths + React-rendered SVG

**Status:** Accepted

**Context.** HANDOVER suggests "d3 or Recharts". The approved mockup is built with d3 and has bespoke elements: limit track with over-limit tick, previous-month line on income bars, faded non-selected months, click-to-select.

**Decision.** Use `d3-scale`, `d3-shape` and `d3-array` (v3) for scales, ticks and paths only. React owns the DOM: each chart is a small typed component under `frontend/src/charts/`. Colours come from CSS variables. The limit bars and income bars are plain HTML/CSS, not SVG.

**Why.** Pixel-faithful to the approved design, tiny bundle, no fighting a chart library's opinions, and full control over a11y (focusable marks, `<title>`, hidden data table).

**Trade-off.** We write tooltip and resize plumbing ourselves (about 100 lines, shared hooks). Recharts would be faster for generic charts but awkward for the limit bars and selection styling.
