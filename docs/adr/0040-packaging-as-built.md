# ADR-0040: Packaging as built (M7)

**Status:** Accepted (2026-11-16, M7 / issue #8). Refines ARCHITECTURE §1, §13 and §16, [ADR-0026](0026-blob-storage.md) and [ADR-0037](0037-data-and-housekeeping-as-built.md).

**Context.** M7 turns Finboard into something a non-developer can run: one image, one compose file, one init command. ARCHITECTURE §16 sketched the commands before anything was built; building it settled the details below. The owner also parked the remaining bank adapters (issue #10) on 2026-11-16, so v1 is packaged with the ICICI savings adapter and the generic fallback.

**Decisions.**

1. **One image for api, worker and beat; an `-ai` variant.**
   - `deploy/Dockerfile` has three stages: node builds the SPA, uv builds the Python environment with the project installed non-editable (the SPA inside the package), and the runtime is `python:3.12-slim-trixie` with neither node nor uv.
   - It runs as uid 10001. `/data` (blobs, backups, the beat schedule) is the only writable path besides `/tmp`.
   - `WITH_AI=1` adds the `ai` extra and runs `finboard ai fetch-model` at build time, so suggestions need no download at run time. The default image stays small (about 540 MB) and can't make the model download at all.
   - **`pg_dump` comes from the PostgreSQL apt repository.** The backup before a migration needs a `pg_dump` at least as new as the server (18); Debian trixie ships 17.
2. **`init` is a separate compose service that runs as root, with no network.**
   - §16 said `docker compose run --rm api finboard init`. But the result has to be a file on the host (`deploy/.env`) that compose reads, and the api container is unprivileged, has a read-only filesystem and can't write to a host directory on Linux.
   - The `init` service (profile `setup`, `network_mode: none`) mounts `deploy/` and runs `finboard init --compose`. It then gives the file to the owner of that directory, so the person who ran it can read their own `.env`.
   - It writes `FINBOARD_SECRET_KEY`, `POSTGRES_PASSWORD`, `FINBOARD_OWNER_PASSWORD` and `FINBOARD_APP_PASSWORD`, and **only adds keys that are missing**. Postgres takes the passwords when its volume is first created, so replacing one would lock the app out of its own database.
   - Passwords are hex, so they need no quoting in a database URL or in the SQL of the Postgres init script.
   - **Why not write to stdout and redirect:** on Windows PowerShell, `>` writes UTF-16 or a BOM, and compose then misreads the file.
   - **Cost:** compose can't mark the variables as required (`${VAR:?}`), because that check also blocks `run init`. Starting without `init` therefore fails at the database container with Postgres's own message. `finboard serve` has a clearer one ("create it with … run --rm init") for the case where only the secret key is missing.
3. **Network layout.** Db, redis, worker and beat are on a network marked `internal`: no route to the host network or the internet, in either direction. The api is on that network and on the default one, which is what lets compose publish it on `127.0.0.1:8765` and lets Ask Finboard reach its provider when the user turns it on. The worker never needs the internet: embedding is local and the model is in the image.
4. **Hardening of the app containers:** read-only root filesystem with a tmpfs `/tmp`, all capabilities dropped, `no-new-privileges`, and `init: true` so hard-killed parser processes are reaped.
5. **One `data` volume, not two.** §1 drew a blobs volume and §16 a backups volume. Both are directories of `/data` in one volume; the beat schedule file lives there too. One volume is one thing to back up.
6. **`FINBOARD_ENV=prod` has a meaning now.** The image sets it. In `prod`:
   - `/api/docs` is off. Swagger UI loads its script and stylesheet from a CDN, which broke the "no CDNs" promise in §13. It stays on in development.
   - `finboard serve` exits with instructions when there is no secret key, instead of starting an app that can't unlock statements.
7. **Users clone the repository.** The stack needs `deploy/compose.yaml` and `deploy/postgres/init/`, which creates the two database roles ([ADR-0025](0025-tenant-isolation-rls.md)). Inlining the script in the compose file would duplicate it. The packaged stack sets `FINBOARD_CREATE_TEST_DB=0`, so it has no `finboard_test` database.
8. **The smoke test is a script, shared by CI and developers.** `scripts/smoke-compose.sh` covers every M7 acceptance row.
   - It runs as its own compose project (`finboard-smoke`), on port 8766, with its `.env` in a temporary directory, and removes its volumes afterwards. It can run on a machine that has a real Finboard without touching it.
   - A host port probe only proves something if the port was closed before the stack started, so the script records that first. The authoritative check is that the containers publish nothing.
   - `scripts/check_bundle.py` reads the built SPA and refuses any absolute URL whose host isn't on a short list of text-only hosts (XML namespaces, links inside library error messages).
9. **Release.** A `vX.Y.Z` tag runs `.github/workflows/release.yml`: it checks the tag against the package version and the changelog, smoke-tests, pushes both variants to GHCR for amd64 and arm64 with SBOM and provenance attestations, and creates the GitHub release from the changelog section with the SBOMs attached. `CHANGELOG.md` is written by hand; the workflow publishes a section, it doesn't generate one.
10. **Name (OQ-19).** The image is `ghcr.io/kapilsharma/finboard`. It is in the owner's namespace, so it can't clash. Nothing is published to PyPI, so that name wasn't checked.

**Consequences.**
- Losing `deploy/.env` while keeping the volumes means losing the database passwords. The README tells users to keep a copy with their backups.
- The release workflow, the arm64 build and the AI features inside the `-ai` image aren't covered by CI. The first tag is their first real run.
- A new setting that users should be able to change has to be passed through in `deploy/compose.yaml`, or the containers never see it.
