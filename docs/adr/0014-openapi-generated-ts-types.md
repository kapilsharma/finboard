# ADR-0014: Frontend API types generated from FastAPI's OpenAPI

**Status:** Accepted

**Decision.** `scripts/gen-api-types` exports `openapi.json` from the app factory (no running server needed) and runs `openapi-typescript` 7 into `frontend/src/api/schema.d.ts`, which is committed. A thin hand-written `fetch` client adds the `X-Finboard-Client` header and problem+json error handling. CI regenerates the types and fails on any diff.

**Why.** One source of truth for shapes, no runtime codegen dependency, and drift caught in CI.
