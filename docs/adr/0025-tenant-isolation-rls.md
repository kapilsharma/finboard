# ADR-0025: Tenant isolation — user_id everywhere, composite FKs, Postgres RLS

**Status:** Accepted

**Decision.** Three independent layers:
1. **Application.** Every repository method takes the `Principal` and filters by `user_id`. Routes never accept a `user_id`.
2. **Schema.** Every user-owned table has `user_id NOT NULL`, with `UNIQUE (user_id, id)`. Cross-table FKs are composite (`(user_id, account_id) REFERENCES account (user_id, id)`), so a row cannot point at another user's row.
3. **Database.** RLS is enabled and `FORCE`d on every user-owned table, with the policy `user_id = current_setting('app.user_id')::uuid`. The runtime role is `NOBYPASSRLS`. `get_uow()` and the worker runtime run `SET LOCAL app.user_id` inside each transaction, which is PgBouncer-safe.

**Tests.** A tenancy suite calls every route as user B with user A's ids and expects 404. Raw-SQL RLS checks run as the app role. An introspection test fails if any table with a `user_id` column lacks a policy.

**Consequences.** Slight query overhead (negligible with `user_id`-leading indexes). Admin and maintenance tasks that span users run as a separate, explicit maintenance role.
