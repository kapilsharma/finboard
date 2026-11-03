# ADR-0027: Statement passwords — ephemeral encrypted handoff API → worker

**Status:** Accepted. Replaces the OS-keychain option from HANDOVER §3 (keychain is unreachable from containers and meaningless on a shared server).

**Context.** Decryption happens in a worker, so the password has to travel there. Celery messages can sit in Redis and appear in logs.

**Decision.** `/unlock` receives the password as `SecretStr`, encrypts it with Fernet using `FINBOARD_SECRET_KEY`, and stores it at `secret:<uuid>` in Redis with a 120 s TTL. The task gets only `secret_ref`. The worker `GETDEL`s it, decrypts it and keeps it in memory for the duration of the parse. Passwords never appear in Postgres, job params, broker messages, blobs or logs. Redis runs with persistence off.

**Saved passwords: none** (owner decision 2026-10-18). The user enters the password at each import. There is no automatic email fetching, so nothing needs a stored password. If that ever changes, it needs a new ADR, because it would relax HANDOVER §3.
