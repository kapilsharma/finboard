#!/usr/bin/env bash
# One-off for a database created before M3a: pgvector must be created by a superuser
# (it isn't a trusted extension). New databases get it from deploy/postgres/init.
#   bash scripts/enable-pgvector.sh            # Docker dev stack (deploy/compose.dev.yaml)
#   bash scripts/enable-pgvector.sh --native   # scripts/setup-native-services.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
for db in finboard finboard_test; do
  sql="CREATE EXTENSION IF NOT EXISTS vector;"
  if [ "${1:-}" = "--native" ]; then
    if [ "$(id -u)" -eq 0 ]; then runuser -u postgres -- psql -p 55432 -d "$db" -c "$sql"
    else sudo -u postgres psql -p 55432 -d "$db" -c "$sql"; fi
  else
    docker compose -f "$ROOT/deploy/compose.dev.yaml" exec -T db psql -U postgres -d "$db" -c "$sql"
  fi
done
echo "pgvector is enabled; run the migrations again (finboard migrate)."
