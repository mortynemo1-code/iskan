#!/usr/bin/env sh
set -eu
postgres_user="${POSTGRES_USER:-workforce}"
postgres_db="${POSTGRES_DB:-workforce}"
for migration in infra/postgres/0*.sql; do
  echo "Applying $migration"
  docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U "$postgres_user" -d "$postgres_db" < "$migration"
done
