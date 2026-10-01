#!/bin/sh
# Creates the farm database (owner role for n8n, read-only role for dashboards and Hermes) and the Phoenix database.
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname n8n <<SQL
CREATE ROLE farm LOGIN PASSWORD '${FARM_DB_PASSWORD}';
CREATE ROLE farm_ro LOGIN PASSWORD '${FARM_RO_PASSWORD}';
CREATE DATABASE farm OWNER farm;
CREATE ROLE phoenix LOGIN PASSWORD '${PHOENIX_DB_PASSWORD}';
CREATE DATABASE phoenix OWNER phoenix;
SQL
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname farm -f /docker-entrypoint-initdb.d/20-schema.sql.in
