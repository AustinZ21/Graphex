#!/bin/sh
set -eu

BACKUP_ROOT=${BACKUP_ROOT:-/backups}
BACKUP_STACK_NAME=${BACKUP_STACK_NAME:-cga}
BACKUP_INTERVAL_SECONDS=${BACKUP_INTERVAL_SECONDS:-3600}
BACKUP_KEEP_COUNT=${BACKUP_KEEP_COUNT:-168}
# PostgreSQL connection — sidecar must have pg_dump available.
PGHOST=${PGHOST:-postgres}
PGPORT=${PGPORT:-5432}
PGUSER=${PGUSER:-app}
PGDATABASE=${PGDATABASE:-appdb}
# PGPASSWORD is expected to be passed in via env from the compose file.
FALKORDB_DATA_DIR=${FALKORDB_DATA_DIR:-/falkordb-data}

export PGHOST PGPORT PGUSER PGDATABASE PGPASSWORD

AUTH_BACKUP_DIR="$BACKUP_ROOT/$BACKUP_STACK_NAME/auth"
FALKOR_BACKUP_DIR="$BACKUP_ROOT/$BACKUP_STACK_NAME/falkordb"

mkdir -p "$AUTH_BACKUP_DIR" "$FALKOR_BACKUP_DIR"

prune_backups() {
  dir="$1"
  pattern="$2"
  keep_count="$3"
  count=0

  for file in $(ls -1t "$dir"/$pattern 2>/dev/null || true); do
    count=$((count + 1))
    if [ "$count" -gt "$keep_count" ]; then
      rm -f "$file"
    fi
  done
}

backup_auth_db() {
  if ! command -v pg_dump >/dev/null 2>&1; then
    echo "[backup] pg_dump not installed; skipping auth backup"
    return 0
  fi

  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  snapshot="$AUTH_BACKUP_DIR/auth-$timestamp.sql.gz"
  tmp="$snapshot.tmp"
  if pg_dump --no-owner --no-privileges --clean --if-exists --format=plain 2>/dev/null | gzip -c > "$tmp"; then
    mv "$tmp" "$snapshot"
    cp "$snapshot" "$AUTH_BACKUP_DIR/auth-latest.sql.gz"
    echo "[backup] auth snapshot -> $snapshot"
    prune_backups "$AUTH_BACKUP_DIR" 'auth-*.sql.gz' "$BACKUP_KEEP_COUNT"
  else
    rm -f "$tmp"
    echo "[backup] pg_dump failed"
  fi
}

backup_falkordb() {
  if [ ! -d "$FALKORDB_DATA_DIR" ]; then
    echo "[backup] FalkorDB data directory not found at $FALKORDB_DATA_DIR"
    return 0
  fi

  timestamp=$(date -u +%Y%m%dT%H%M%SZ)
  snapshot="$FALKOR_BACKUP_DIR/falkordb-$timestamp.tgz"
  tar -czf "$snapshot" -C "$FALKORDB_DATA_DIR" .
  cp "$snapshot" "$FALKOR_BACKUP_DIR/falkordb-latest.tgz"
  echo "[backup] FalkorDB snapshot -> $snapshot"
  prune_backups "$FALKOR_BACKUP_DIR" 'falkordb-*.tgz' "$BACKUP_KEEP_COUNT"
}

backup_once() {
  backup_auth_db
  backup_falkordb
}

echo "[backup] starting periodic runtime backup loop for $BACKUP_STACK_NAME"
backup_once

while true; do
  sleep "$BACKUP_INTERVAL_SECONDS"
  backup_once
done
