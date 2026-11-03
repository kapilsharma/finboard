# ADR-0015: Same origin everywhere (Vite proxy), no CORS; Host + Origin + custom-header CSRF guard

**Status:** Accepted (owner, 2026-10-18). Changes HANDOVER §7's "CORS only for the dev frontend origin".

**Context.** Any website the user visits can send *simple* cross-origin requests (form POST, multipart upload) to `127.0.0.1:8765`. CORS does not block sending them, and the Host header in such a request is legitimately `127.0.0.1`, so the Host check alone doesn't help. DNS rebinding is the separate threat that the Host check *does* stop.

**Decision.**
1. Dev: Vite proxies `/api` → `127.0.0.1:8765` with `changeOrigin: false`, so the backend sees `Host` = the page's host, which matches the browser's `Origin` header. The browser only ever talks to one origin, so **no CORS middleware at all**, in dev or prod.
2. Host allow-list middleware (`127.0.0.1`, `localhost`, `[::1]` + configured port) → 421 otherwise.
3. All non-GET/HEAD requests must carry `X-Finboard-Client: 1` (a non-simple header forces a preflight we never approve), and if `Origin` is present it must equal our own origin → 403 otherwise.
4. No cookies or other ambient credentials exist.

**Consequences.** Stronger than the handover's plan for the same effort. GET endpoints must stay side-effect-free: only mutating service methods commit (enforced in review).

**Server mode (future, [ADR-0021](0021-multi-user-ready-single-user-first.md)).** Once session cookies exist, add a cookie-bound CSRF token (double-submit) and `SameSite=Strict`. The Host allow-list then becomes the configured public hostname. CORS stays off as long as the SPA is served from the same origin.
