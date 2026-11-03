# ADR-0026: BlobStore abstraction for uploaded and archived statements

**Status:** Accepted

**Decision.** A `BlobStore` protocol (`put`, `get`, `delete`, `exists`) with async methods. v1 ships `LocalFsBlobStore` on a Docker volume shared by api and worker. An `S3BlobStore` (any S3-compatible service) can be added later. Keys are generated: `users/<user_id>/imports/<import_id>`. File names never become paths. Stored bytes are always the **original** (still bank-encrypted) file. Archiving is on by default (OQ-5); an archived blob is simply kept after commit.

**Why.** Postgres is a poor place for binaries. API and workers must share files without sharing a filesystem once hosted.
