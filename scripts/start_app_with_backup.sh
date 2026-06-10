#!/bin/sh
set -eu

if [ "${BACKUP_ENABLED:-1}" = "1" ]; then
  echo "[startup] Launching backup scheduler..." >&2
  python /app/scripts/backup_postgres.py \
    --backup-dir /app/backups \
    --db-host "${BACKUP_POSTGRES_HOST:-db}" \
    --db-port "${BACKUP_POSTGRES_PORT:-5432}" \
    --interval-hours "${BACKUP_INTERVAL_HOURS:-24}" \
    --retention-days "${BACKUP_RETENTION_DAYS:-30}" &
fi

echo "[startup] Launching application..." >&2
exec python /app/main.py
