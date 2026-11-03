# ADR-0008: Money as NUMERIC(14,2) / Decimal / decimal strings

**Status:** Accepted (revised 2026-10-18 for PostgreSQL; previously "integer paise", which was a SQLite workaround)

**Decision.**
- DB: `NUMERIC(14,2)` (max ₹99,99,99,99,999.99), always positive, sign in `direction`. `CHECK (amount > 0)`.
- Python: `Decimal` quantised to `0.01` (`domain.money`). asyncpg returns `Decimal` natively. Floats raise `TypeError` at construction.
- API/JSON: decimal **strings** (`"2350.00"`). Pydantic serialises `Decimal` as a string via a shared `Money` annotated type.
- Frontend: never does arithmetic on money; converts to `number` for chart geometry only.

**Why.** Postgres NUMERIC is exact, so there's no need for an integer-paise workaround. `SUM()` stays exact, values are readable in `psql`, and no conversion layer is needed.
