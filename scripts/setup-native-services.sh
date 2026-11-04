#!/usr/bin/env bash
# Install and start PostgreSQL 18 + Redis 7 natively, for environments without Docker
# (e.g. cloud agent sandboxes). Produces the same setup as deploy/compose.dev.yaml:
#   Postgres on 127.0.0.1:55432 with roles finboard_owner / finboard_app and databases
#   finboard + finboard_test;  Redis on 127.0.0.1:56379 without persistence.
# Debian/Ubuntu only. Safe to re-run.
set -euo pipefail

PG_MAJOR=18
PG_PORT=55432
REDIS_PORT=56379
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; AS_POSTGRES="runuser -u postgres --"; else SUDO="sudo"; AS_POSTGRES="sudo -u postgres"; fi
export DEBIAN_FRONTEND=noninteractive

echo "==> packages"
$SUDO apt-get update -qq
$SUDO apt-get install -y -qq curl ca-certificates gnupg lsb-release redis-server >/dev/null
if [ ! -x "/usr/lib/postgresql/${PG_MAJOR}/bin/postgres" ]; then
  $SUDO install -d /usr/share/postgresql-common/pgdg
  $SUDO curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    https://www.postgresql.org/media/keys/ACCC4CF8.asc
  echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" \
    | $SUDO tee /etc/apt/sources.list.d/pgdg.list >/dev/null
  $SUDO apt-get update -qq
  # From M3a also: postgresql-${PG_MAJOR}-pgvector
  $SUDO apt-get install -y -qq "postgresql-${PG_MAJOR}" "postgresql-${PG_MAJOR}-pgvector" >/dev/null
fi

echo "==> postgres ${PG_MAJOR} on port ${PG_PORT}"
if ! $SUDO pg_lsclusters -h | awk '{print $1" "$2}' | grep -q "^${PG_MAJOR} main$"; then
  $SUDO pg_createcluster "${PG_MAJOR}" main --port "${PG_PORT}" >/dev/null
fi
$SUDO pg_conftool "${PG_MAJOR}" main set port "${PG_PORT}"
$SUDO pg_ctlcluster "${PG_MAJOR}" main restart 2>/dev/null || $SUDO pg_ctlcluster "${PG_MAJOR}" main start

if ! $AS_POSTGRES psql -p "${PG_PORT}" -tAc "SELECT 1 FROM pg_roles WHERE rolname = 'finboard_app'" | grep -q 1; then
  echo "==> roles and databases (deploy/postgres/init/01-finboard.sh)"
  $AS_POSTGRES env PGPORT="${PG_PORT}" POSTGRES_USER=postgres \
    FINBOARD_OWNER_PASSWORD=finboard_owner_dev FINBOARD_APP_PASSWORD=finboard_app_dev \
    sh "${REPO_ROOT}/deploy/postgres/init/01-finboard.sh"
fi

echo "==> redis on port ${REDIS_PORT}"
if ! redis-cli -p "${REDIS_PORT}" ping >/dev/null 2>&1; then
  redis-server --port "${REDIS_PORT}" --bind 127.0.0.1 --save "" --appendonly no --daemonize yes >/dev/null
fi

redis-cli -p "${REDIS_PORT}" ping >/dev/null
PGPASSWORD=finboard_app_dev psql -h 127.0.0.1 -p "${PG_PORT}" -U finboard_app -d finboard_test -tAc "SELECT 'postgres ok'"
echo "==> ready: postgres 127.0.0.1:${PG_PORT}, redis 127.0.0.1:${REDIS_PORT}"
