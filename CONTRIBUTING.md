# Contributing

Thanks for helping! Start with [README.md](README.md) for setup and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit.

## Ground rules

1. **No real financial data, ever.** Not in code, tests, fixtures, issues or screenshots. Use the
   synthetic fixture builders, and redact anything you paste.
2. **Respect the layers** (`api → services → db → domain`). `uv run lint-imports` checks them.
3. **Every user-owned table gets row-level security.** Add `user_id`, a `(user_id, id)` unique key,
   composite foreign keys, and `enable_user_rls()` in the migration. Add the table to
   `USER_OWNED_TABLES`. The tenancy tests fail if you forget.
4. **Money is `Decimal` / `NUMERIC(14,2)`**, never float. It crosses the API as a decimal string.
5. Significant design changes get a short ADR in `docs/adr/`.

## Before opening a pull request

```sh
cd backend  && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy && uv run lint-imports && uv run pytest
cd frontend && npm run lint && npm run format:check && npm run typecheck && npm test
```

If you changed the API, run `npm run gen:api` in `frontend/` and commit `src/api/schema.d.ts`.

## How to add your bank

*Arrives with the parser SDK in M2.* In short: copy the template adapter, write a fixture builder
that reproduces your bank's statement **layout** with fake data, implement `detect` and `parse`,
and run the parser contract tests. You can share a statement's structure safely with
`finboard inspect-layout statement.pdf`, which masks every digit and letter.
