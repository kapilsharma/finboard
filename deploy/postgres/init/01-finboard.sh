#!/bin/sh
# Runs once, on first start of an empty data volume (docker-entrypoint-initdb.d).
# Creates two roles (ADR-0025):
#   finboard_owner — owns the databases and runs migrations
#   finboard_app   — runtime role; NOBYPASSRLS so row-level security always applies
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<SQL
CREATE ROLE finboard_owner LOGIN PASSWORD '${FINBOARD_OWNER_PASSWORD}';
CREATE ROLE finboard_app LOGIN PASSWORD '${FINBOARD_APP_PASSWORD}' NOBYPASSRLS;
CREATE DATABASE finboard OWNER finboard_owner;
CREATE DATABASE finboard_test OWNER finboard_owner;
SQL

for db in finboard finboard_test; do
  psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$db" <<SQL
REVOKE ALL ON DATABASE $db FROM PUBLIC;
GRANT CONNECT ON DATABASE $db TO finboard_app;
GRANT USAGE ON SCHEMA public TO finboard_app;
ALTER DEFAULT PRIVILEGES FOR ROLE finboard_owner IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO finboard_app;
ALTER DEFAULT PRIVILEGES FOR ROLE finboard_owner IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO finboard_app;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS citext;
SQL
done
