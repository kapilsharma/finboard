# ADR-0029: Observability without telemetry

**Status:** Accepted

**Decision.** structlog JSON logs, with `request_id` (from or set as `X-Request-ID`), `user_id` (opaque UUID), `job_id` and timings bound via contextvars in the API and Celery. A redaction processor drops known sensitive keys (`password`, `description*`, `amount*`, `file_name`). Probes: `/health/live` and `/health/ready` (DB + Redis). OpenTelemetry instrumentation (FastAPI, SQLAlchemy, Celery) is wired in but **disabled unless `OTEL_EXPORTER_OTLP_ENDPOINT` is set**. Nothing is ever sent anywhere by default.

**Why.** This is what a large FastAPI system needs operationally, and it doesn't break the "no telemetry" principle.
