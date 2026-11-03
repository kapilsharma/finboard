# ADR-0002: Python + FastAPI backend

**Status:** Accepted (given — HANDOVER §2)

**Decision.** Python ≥ 3.12 with FastAPI (`>=0.115,<1`), Pydantic 2, uvicorn. PDF stack: pdfplumber 0.11, pikepdf (current major), camelot as an optional extra (`finboard[camelot]`), because it pulls heavy dependencies (OpenCV/Ghostscript) that most parsers won't need.

**Consequences.** Best PDF tooling available. Routes are `async` ([ADR-0023](0023-async-sqlalchemy.md)). The sync, CPU-bound PDF work runs in Celery workers ([ADR-0024](0024-celery-redis-jobs.md)).
