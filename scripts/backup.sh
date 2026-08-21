#!/usr/bin/env sh
set -eu

backup_dir="${WORKFORCE_BACKUP_DIR:-./backups}"
retention_days="${WORKFORCE_BACKUP_RETENTION_DAYS:-30}"
postgres_user="${POSTGRES_USER:-workforce}"
postgres_db="${POSTGRES_DB:-workforce}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
umask 077

docker compose exec -T postgres pg_dump -U "$postgres_user" -d "$postgres_db" -Fc > "$backup_dir/postgres-$timestamp.dump"
docker compose exec -T redis redis-cli BGSAVE >/dev/null
docker run --rm --volumes-from "$(docker compose ps -q redis)" -v "$(cd "$backup_dir" && pwd):/backup" alpine:3.22 \
  tar -czf "/backup/redis-$timestamp.tar.gz" -C /data dump.rdb
find "$backup_dir" -type f -mtime "+$retention_days" -name 'postgres-*.dump' -delete
find "$backup_dir" -type f -mtime "+$retention_days" -name 'redis-*.tar.gz' -delete
echo "Backup completed: $timestamp"
