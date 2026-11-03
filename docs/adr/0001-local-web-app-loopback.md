# ADR-0001: Local web app served on 127.0.0.1

**Status:** Accepted (given — HANDOVER §2), **amended** by [ADR-0021](0021-multi-user-ready-single-user-first.md) on 2026-10-18.

**Context.** Bank data must stay on the user's machine.

**Decision.** v1 runs on the owner's machine, with the app published only on `127.0.0.1`, now via Docker Compose. Browser-only/GitHub Pages is rejected. Electron/Tauri is deferred.

**Amendment.** The architecture is built so the same images can later be hosted for many users (ADR-0021). Local, loopback-only deployment remains the v1 default and the only documented setup.

**Consequences.** Loopback alone does not stop CSRF or DNS rebinding, so the checks in [ADR-0015](0015-dev-proxy-no-cors-csrf-header.md) are required.
