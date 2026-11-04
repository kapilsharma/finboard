#!/usr/bin/env bash
# Run the same checks as GitHub Actions (.github/workflows/ci.yml) locally.
# Keep the two in sync: a step added there belongs here too.
#
#   scripts/ci-local.sh              everything (as CI does)
#   scripts/ci-local.sh --fast       skip dependency installs and the production build
#   scripts/ci-local.sh --backend    backend only        (combine with --fast)
#   scripts/ci-local.sh --frontend   frontend only + generated API types check
#
# Integration tests need Postgres 18 on 127.0.0.1:55432 and Redis on 127.0.0.1:56379:
#   docker compose -f deploy/compose.dev.yaml up -d      (with Docker)
#   bash scripts/setup-native-services.sh                (Debian/Ubuntu, without Docker)
# Exit code is non-zero if any step fails; it stops at the first failure.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAST=0
BACKEND=1
FRONTEND=1

for arg in "$@"; do
  case "$arg" in
    --fast) FAST=1 ;;
    --backend) FRONTEND=0 ;;
    --frontend) BACKEND=0 ;;
    -h | --help) sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done
if [ "$BACKEND" = 0 ] && [ "$FRONTEND" = 0 ]; then
  BACKEND=1; FRONTEND=1   # --backend --frontend together means both
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv is not on PATH. Install it: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 2
fi
if [ "$FRONTEND" = 1 ] && ! command -v npm >/dev/null 2>&1; then
  echo "npm is not on PATH (Node 22+ required)." >&2
  exit 2
fi

STARTED=$(date +%s)
PASSED=()

step() {
  local name="$1"; shift
  local t0=$SECONDS
  printf '\n\033[1m==> %s\033[0m\n' "$name"
  if "$@"; then
    PASSED+=("$name ($((SECONDS - t0))s)")
  else
    printf '\n\033[31mFAILED: %s\033[0m\n' "$name" >&2
    printf 'Passed before the failure:\n' >&2
    printf '  - %s\n' "${PASSED[@]+"${PASSED[@]}"}" >&2
    exit 1
  fi
}

in_backend() { (cd "$ROOT/backend" && "$@"); }
in_frontend() { (cd "$ROOT/frontend" && "$@"); }

services_up() {
  # Fail fast with instructions instead of a wall of connection errors from pytest.
  in_backend uv run --frozen python - <<'PY'
import socket, sys
missing = []
for name, port in (("Postgres", 55432), ("Redis", 56379)):
    try:
        socket.create_connection(("127.0.0.1", port), timeout=2).close()
    except OSError:
        missing.append(f"{name} on 127.0.0.1:{port}")
if missing:
    print("Not reachable: " + ", ".join(missing), file=sys.stderr)
    print("Start them with one of:", file=sys.stderr)
    print("  docker compose -f deploy/compose.dev.yaml up -d", file=sys.stderr)
    print("  bash scripts/setup-native-services.sh   (Debian/Ubuntu, no Docker)", file=sys.stderr)
    sys.exit(1)
print("Postgres and Redis are reachable")
PY
}

api_types_current() {
  in_frontend npm run --silent gen:api >/dev/null || return 1
  if ! git -C "$ROOT" diff --quiet -- frontend/src/api/schema.d.ts; then
    echo "frontend/src/api/schema.d.ts is out of date: commit the regenerated file." >&2
    git -C "$ROOT" --no-pager diff --stat -- frontend/src/api/schema.d.ts >&2
    return 1
  fi
}

# --- privacy (job: privacy)
step "No private data in the repo" in_backend uv run --no-project python ../scripts/check_no_private_data.py

# --- backend (jobs: lint [backend part], backend-integration)
if [ "$BACKEND" = 1 ]; then
  [ "$FAST" = 1 ] || step "Backend: install (uv sync --locked)" in_backend uv sync --locked
  step "Backend: ruff check" in_backend uv run --frozen ruff check src tests
  step "Backend: ruff format --check" in_backend uv run --frozen ruff format --check src tests
  step "Backend: mypy (strict)" in_backend uv run --frozen mypy
  step "Backend: import layers" in_backend uv run --frozen lint-imports
  step "Backend: Postgres + Redis reachable" services_up
  step "Backend: pytest (unit + integration + tenancy)" in_backend uv run --frozen pytest -q
fi

# --- frontend (jobs: lint [frontend part], frontend)
if [ "$FRONTEND" = 1 ]; then
  [ "$FAST" = 1 ] || step "Frontend: install (npm ci)" in_frontend npm ci --no-audit --no-fund
  step "Frontend: oxlint" in_frontend npm run --silent lint
  step "Frontend: prettier --check" in_frontend npm run --silent format:check
  step "Frontend: typecheck" in_frontend npm run --silent typecheck
  step "Frontend: vitest" in_frontend npm test --silent
  [ "$FAST" = 1 ] || step "Frontend: production build" in_frontend npm run --silent build
  # (job: lint, "Generated API types are up to date") needs the backend too.
  step "Generated API types are up to date" api_types_current
fi

printf '\n\033[32mAll checks passed\033[0m in %ss:\n' "$(( $(date +%s) - STARTED ))"
printf '  - %s\n' "${PASSED[@]}"
