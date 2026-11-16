# ADR-0041: Server mode as built: sessions, sign-up, limits, S3 (M8)

**Status:** Accepted (2026-11-16, M8 / issue #21). Completes [ADR-0021](0021-multi-user-ready-single-user-first.md); refines ARCHITECTURE §4, §13 and §14, [ADR-0015](0015-dev-proxy-no-cors-csrf-header.md) and [ADR-0026](0026-blob-storage.md). Resolves OQ-23.

**Context.** Finboard was built for many users from M1 (tenancy, RLS, stateless API), but shipped with one fixed `local` user and `FINBOARD_MODE=server` refused to start. M8 turns sign-in on. Local mode stays the default and is unchanged.

**Decisions.**

1. **Own passwords, argon2id** (OQ-23). `argon2-cffi` with its defaults; hashes carry their parameters and are upgraded at the next sign-in when the defaults rise.
   - The hash is a nullable column on `app_user`, which has no row-level security. Sign-in has to look a user up before anyone is known, and a separate credentials table with a `user_id` would have needed an RLS exception.
   - NULL means "can't sign in with a password": the `local` user of a local-mode database. `finboard set-password local` is the migration path from local to server mode.
   - Policy is length only (10 to 128 characters, not the username). No composition rules.
   - A wrong username costs the same work and returns the same answer as a wrong password, so neither the response nor its timing says which accounts exist.
2. **Sessions are server-side, in Redis.**
   - The cookie holds a random 256-bit id. Redis stores its SHA-256, so a Redis dump can't be replayed as cookies.
   - Cookie: `HttpOnly`, `SameSite=Strict`, `Path=/`. Over https it is `Secure` and named `__Host-finboard_session`, which browsers refuse to accept from a sibling subdomain.
   - A session ends after 7 days unused and at 30 days regardless. Signing out, changing the password or an operator's `set-password` ends sessions at once. That immediacy is why these aren't signed stateless tokens.
   - The session carries the user's id and names, so an ordinary request needs no database query to authenticate: one Redis read.
3. **A session-bound CSRF token, on top of what local mode already has.** `SameSite=Strict`, the `X-Finboard-Client` header and the Origin check (ADR-0015) already stop cross-site requests. Each session also has a random token, returned by `/auth/login` and `/me`, that must come back in `X-CSRF-Token` on every request that changes something. It doesn't depend on browser behaviour, and it lives only in the page's memory.
   - `AuthBackend.authenticate` gained a `method` argument so the backend can apply this. A missing or wrong token is 403 `csrf_check_failed`.
4. **Sign-up is closed by default.** `FINBOARD_SIGNUP=open` lets anyone who can reach the server create an account; otherwise the operator runs `finboard create-user`. An operator who forgets a setting should end up with the safer server. The sign-in page reads `signup_open` from `/meta` and offers sign-up only then.
5. **Server mode refuses unsafe configurations.** It needs `FINBOARD_PUBLIC_URL`. Plain http is accepted only for a loopback host (trying it out on one machine); anything else must be https. The URL's host joins the Host allow-list and decides the cookie's `Secure` flag. TLS itself is the reverse proxy's job (docs/HOSTING.md).
6. **Limits, all in Redis, all per user or per address** (`storage/ratelimit.py`, fixed windows):
   - sign-in: 5 wrong passwords per account, and 30 per address, lock sign-in for 15 minutes; a success clears the account's count;
   - sign-up: 5 per address per hour;
   - requests: 600 per user per minute;
   - uploads: 60 per user per hour;
   - storage: 5 GB of stored statements per user, measured as the sizes of imports that still have a file.
   - Keys never contain what someone typed: usernames and addresses are hashed.
   - Over a limit is 429 `rate_limited` with `Retry-After`, or 413 `storage_quota_exceeded`.
   - None of these apply in local mode.
7. **`S3BlobStore`** implements the existing `BlobStore` protocol with boto3, in the optional `s3` extra and a `-s3` image. boto3 is synchronous, so calls run in threads, like the local store's file access. `build_blob_store(settings)` gives the API and the workers the same store.
   - This is a second outbound path besides Ask Finboard, and like it, it exists only when the operator configures it. Statements are stored as uploaded, still bank-encrypted.
8. **No account pages beyond the essentials.** Sign in, sign up, sign out, change password. No email, so no password reset by email: the operator resets with `finboard set-password`. No admin UI, no two-factor sign-in. OIDC remains the planned next step.
9. **The tenancy suite runs twice, unchanged.** With `FINBOARD_TEST_AUTH=session` the test app starts in server mode with `SessionBackend`; alice and bob sign in through `/auth/login`; and the test client turns a test's `X-Test-User: bob` header into bob's real cookie and CSRF token. Only the fixtures know. CI runs `tests/integration/tenancy` both ways.

**Load test (ROADMAP M8).** 300 signed-in users, each with their own data, on the owner's laptop (8 logical cores, Windows, Postgres in Docker, Locust on the same machine):

| Setup | Requests | Failures | Requests/s | Median | p95 |
|---|---|---|---|---|---|
| Server mode, 3 API processes, 100 users | 4,599 | 0 | 83 | 45 ms | 140 ms |
| Server mode, 6 API processes, 300 users | 20,152 | 0 | 168 | 510 ms | 1,500 ms |
| Local mode (no sessions), 6 API processes, 300 users | 19,051 | 0 | 158 | 590 ms | 1,800 ms |

- 300 users work, with no errors, but this machine saturates at about 160 requests a second, so the M4 budget (p95 < 300 ms) is **not met at 300 users here**. It is met at 100.
- Sessions aren't the cost: the same load without them is no faster.
- 6 API processes with the default pool (10 + 10 connections each) exhausted Postgres's 100 connections and returned 500s. The server compose file now sets 8 + 4, and HOSTING.md gives the sizing rule.

**Consequences.**
- Redis now holds something users notice: restarting it signs everyone out.
- `app_user` holds password hashes and is readable by the application role without RLS. The Ask Finboard SQL path never touches Postgres ([ADR-0032](0032-nl-analytics-langgraph.md)), so model-written SQL can't reach it.
- An operator can read everything. Server mode separates users from each other, not from whoever runs the server.
- Not built: account deletion by the user (delete-all removes the data, the account row stays), deactivating an account from the CLI, and audit logging of sign-ins beyond the request log.
