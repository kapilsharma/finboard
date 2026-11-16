#!/usr/bin/env bash
# Smoke test of the packaged stack (deploy/compose.yaml): the ROADMAP M7 acceptance rows.
#
#   scripts/smoke-compose.sh            build the image from this checkout, then test it
#   scripts/smoke-compose.sh --e2e      also run the Playwright happy path against the stack
#   FINBOARD_IMAGE=ghcr.io/...:1.0.0 scripts/smoke-compose.sh --no-build    test a pulled image
#
# It runs as its own compose project (`finboard-smoke`, port 8766, its own .env in a temporary
# directory), so it never touches a real Finboard on this machine. Everything it creates,
# volumes included, is removed at the end. Needs Docker with the compose plugin and python3.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD=1
E2E=0
for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD=0 ;;
    --e2e) E2E=1 ;;
    -h | --help) sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (see --help)" >&2; exit 2 ;;
  esac
done

PYTHON="$(command -v python3 || command -v python)"
CONF="$(mktemp -d)"
# Git Bash on Windows: give Docker Windows paths, and stop MSYS rewriting the container paths
# passed to `docker compose exec`.
if command -v cygpath >/dev/null 2>&1; then
  CONF="$(cygpath -m "$CONF")"
  ROOT="$(cygpath -m "$ROOT")"
  export MSYS_NO_PATHCONV=1
fi

export FINBOARD_PORT="${SMOKE_PORT:-8766}"
export FINBOARD_CONFIG_DIR="$CONF"
export FINBOARD_IMAGE="${FINBOARD_IMAGE:-finboard:smoke}"
BASE="http://127.0.0.1:$FINBOARD_PORT"

FILES=(-f "$ROOT/deploy/compose.yaml")
[ "$BUILD" = 1 ] && FILES+=(-f "$ROOT/deploy/compose.build.yaml")
compose() { docker compose -p finboard-smoke --env-file "$CONF/.env" "${FILES[@]}" "$@"; }

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }
fail() { printf '\033[31mFAILED: %s\033[0m\n' "$*" >&2; exit 1; }

cleanup() {
  status=$?
  if [ "$status" != 0 ]; then
    echo "--- container status and recent logs" >&2
    compose ps -a >&2 || true
    compose logs --tail 40 >&2 || true
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$CONF"
  exit "$status"
}
trap cleanup EXIT

port_open() {
  "$PYTHON" - "$1" <<'PY'
import socket, sys
try:
    socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=2).close()
except OSError:
    sys.exit(1)
PY
}

# GET a JSON document from the API and print one value from it: api_value PATH PYTHON_EXPR
api_value() {
  curl -fsS "$BASE/api/v1$1" | "$PYTHON" -c "import json, sys; d = json.load(sys.stdin); print($2)"
}

# Something else on this machine may already listen on the default ports (a dev database).
# Only a port that was closed before the stack came up can prove anything afterwards.
PROBE_PORTS=()
for port in 5432 6379; do
  port_open "$port" || PROBE_PORTS+=("$port")
done

touch "$CONF/.env" # compose needs the file to exist before `init` fills it
if [ "$BUILD" = 1 ]; then
  say "Build the image"
  compose build api
fi

say "finboard init writes the secret key and passwords, once"
compose run --rm init
for key in FINBOARD_SECRET_KEY POSTGRES_PASSWORD FINBOARD_OWNER_PASSWORD FINBOARD_APP_PASSWORD; do
  grep -q "^$key=.\{20,\}" "$CONF/.env" || fail "$key is missing from the generated .env"
done
before="$(cksum <"$CONF/.env")"
compose run --rm init
[ "$before" = "$(cksum <"$CONF/.env")" ] || fail "a second init changed .env"
[ -r "$CONF/.env" ] || fail ".env isn't readable by the user who ran init"

say "Start the stack"
compose up -d --wait
[ "$(api_value /health/ready 'd["status"]')" = "ok" ] || fail "/health/ready is not ok"
curl -fsS "$BASE/" | grep -q '<div id="root">' || fail "the app isn't served at /"

say "The image runs as non-root; only the api is published, on loopback"
for service in api worker beat; do
  uid="$(compose exec -T "$service" id -u)"
  [ "$uid" != 0 ] || fail "$service runs as root"
done
[ "$(docker image inspect "$FINBOARD_IMAGE" --format '{{.Config.User}}')" = "10001:10001" ] ||
  fail "the image's default user is not the unprivileged one"
for service in db redis worker beat; do
  published="$(docker inspect "$(compose ps -q "$service")"     --format '{{range $port, $bindings := .NetworkSettings.Ports}}{{if $bindings}}{{$port}} {{end}}{{end}}')"
  [ -z "$published" ] || fail "$service publishes $published"
done
compose ps --format '{{.Ports}}' api | grep -q "127.0.0.1:$FINBOARD_PORT->8000/tcp" ||
  fail "the api isn't published on 127.0.0.1:$FINBOARD_PORT"
compose ps --format '{{.Ports}}' api | grep -q '0\.0\.0\.0\|\[::\]' &&
  fail "the api is published on every interface"
for port in "${PROBE_PORTS[@]+"${PROBE_PORTS[@]}"}"; do
  port_open "$port" && fail "port $port became reachable from the host"
  echo "port $port: not reachable from the host"
done
[ "${#PROBE_PORTS[@]}" = 2 ] || echo "(a host port was already in use before the test; probed the rest)"

say "The worker runs jobs"
job="$(curl -fsS -X POST -H 'X-Finboard-Client: 1' "$BASE/api/v1/jobs/ping" |
  "$PYTHON" -c 'import json, sys; print(json.load(sys.stdin)["id"])')"
status=queued
for _ in $(seq 1 30); do
  status="$(api_value "/jobs/$job" 'd["status"]')"
  [ "$status" = succeeded ] && break
  sleep 1
done
[ "$status" = succeeded ] || fail "the ping job ended as '$status'"

say "Load the synthetic demo data"
compose exec -T api finboard demo-data

if [ "$E2E" = 1 ]; then
  say "Playwright happy path against the packaged stack"
  (cd "$ROOT/e2e" && E2E_BASE_URL="$BASE" npx playwright test)
fi

say "Data survives down / up"
count="$(api_value '/transactions?limit=1' 'd["total"]')"
[ "$count" -gt 0 ] || fail "no transactions to check persistence with"
compose down
compose up -d --wait
after="$(api_value '/transactions?limit=1' 'd["total"]')"
[ "$count" = "$after" ] || fail "$count transactions before the restart, $after after"
echo "$after transactions before and after"

say "The image holds no statements, dumps or outside URLs"
found="$(compose exec -T --user 0 api find / -xdev -type f \
  \( -iname '*.pdf' -o -iname '*.dump' -o -iname '*.sqlite' -o -iname '*.sqlite3' \
  -o -iname '*.zip' -o -iname '*.xls' -o -iname '*.xlsx' -o -name '.env' \) \
  -not -path '/data/*' -not -path '/proc/*' 2>/dev/null || true)"
[ -z "$found" ] || fail "unexpected files in the image: $found"
static="$(compose exec -T api python -c \
  'import finboard, pathlib; print(pathlib.Path(finboard.__file__).parent / "web" / "static")')"
compose exec -T api python - "$static" <"$ROOT/scripts/check_bundle.py"
curl -s -o /dev/null -w '%{http_code}' "$BASE/api/docs" | grep -q 404 ||
  fail "/api/docs (Swagger UI, which loads from a CDN) is served by the packaged app"

printf '\n\033[32mPackaged stack: all smoke checks passed\033[0m\n'
