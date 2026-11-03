# ADR-0013: State = TanStack Query (server) + URL (UI); no global store

**Status:** Accepted

**Decision.** TanStack Query 5 holds all server data and invalidates by key after mutations. Month, filters and sort live in URL search params via a typed `useUrlState` hook. Theme and other small cross-cutting state use React context. No Redux/Zustand.

**Why.** Almost all state is server state. URL state gives "filters persist when month changes", back-button behaviour and shareable links for free.

**Revisit if** a complex client-only workflow appears, such as multi-file import queue orchestration. Even then, start with a local reducer.
