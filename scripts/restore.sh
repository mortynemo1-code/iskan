#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then echo "Usage: $0 backups/postgres-TIMESTAMP.dump" >&2; exit 2; fi
dump_file="$1"
postgres_user="${POSTGRES_USER:-workforce}"
postgres_db="${POSTGRES_DB:-workforce}"
if [ ! -f "$dump_file" ]; then echo "Dump not found: $dump_file" >&2; exit 2; fi

echo "Restore replaces the current PostgreSQL database. Set WORKFORCE_CONFIRM_RESTORE=YES to continue."
if [ "${WORKFORCE_CONFIRM_RESTORE:-}" != "YES" ]; then exit 3; fi
docker compose exec -T postgres dropdb -U "$postgres_user" --if-exists "$postgres_db"
docker compose exec -T postgres createdb -U "$postgres_user" "$postgres_db"
docker compose exec -T postgres pg_restore -U "$postgres_user" -d "$postgres_db" --clean --if-exists < "$dump_file"
echo "Restore completed"
