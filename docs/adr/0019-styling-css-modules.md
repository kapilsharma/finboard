# ADR-0019: Styling with CSS Modules + CSS custom properties

**Status:** Accepted

**Decision.** Component styles live in CSS Modules. Design tokens are CSS variables in `theme/tokens.css` with light, dark and `prefers-color-scheme` variants. Charts read the same variables. No Tailwind and no component kit. For the few primitives where accessibility is hard to hand-roll (dialog, select, popover), use Radix UI primitives.

**Why.** Zero runtime, built into Vite, easy to match the mockup's restrained look, and simple for contributors to read.
