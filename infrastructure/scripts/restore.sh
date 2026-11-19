#!/usr/bin/env bash
# Restore a Docker Compose backup into a NEW database by default.
# Documents are restored to a separate bucket/directory unless you override it.
set -euo pipefail

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup-dir> [database] [target-bucket]" >&2
  exit 2
fi

BACKUP_DIR="$1"
DATABASE="${2:-resolve_restore_$(date +%Y%m%d_%H%M%S)}"
TARGET_BUCKET="${3:-}"
if ! [[ "$DATABASE" =~ ^[A-Za-z0-9_]+$ ]]; then
  echo "Invalid database name: $DATABASE" >&2
  exit 2
fi
if [ ! -f "$BACKUP_DIR/database.dump" ]; then
  echo "database.dump not found in $BACKUP_DIR" >&2
  exit 1
fi

envval() { grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'; }
POSTGRES_USER="${POSTGRES_USER:-$(envval POSTGRES_USER)}"
POSTGRES_USER="${POSTGRES_USER:-resolve}"
BACKEND="$(grep '^storage_backend=' "$BACKUP_DIR/manifest.env" | cut -d= -f2-)"
SOURCE_BUCKET="$(grep '^bucket=' "$BACKUP_DIR/manifest.env" | cut -d= -f2-)"
BACKEND="${BACKEND:-s3}"

EXISTS="$(docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -t -A -c "select 1 from pg_database where datname='$DATABASE'")"
if [ "$EXISTS" = "1" ]; then
  echo "Database $DATABASE already exists. Choose another name." >&2
  exit 1
fi

echo "Restoring database into $DATABASE..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE $DATABASE"
docker compose cp "$BACKUP_DIR/database.dump" postgres:/tmp/resolve-restore.dump
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$DATABASE" \
  --no-owner --no-privileges /tmp/resolve-restore.dump
docker compose exec -T postgres rm -f /tmp/resolve-restore.dump

echo "Verifying restored rows..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$DATABASE" -t -A -F "=" -c "
select 'organizations', count(*) from organizations
union all select 'invoices', count(*) from invoices
union all select 'documents', count(*) from documents
union all select 'cases', count(*) from cases
union all select 'audit_logs', count(*) from audit_logs
union all select 'document_chunks', count(*) from document_chunks;
"

if [ "$BACKEND" = "local" ]; then
  if [ ! -f "$BACKUP_DIR/storage/documents.tar.gz" ]; then
    echo "No local document archive found; skipping documents." >&2
  else
    TARGET="${BACKUP_DIR}/restored-storage"
    mkdir -p "$TARGET"
    TARGET_ABS="$(cd "$TARGET" && pwd)"
    BACKUP_ABS="$(cd "$BACKUP_DIR" && pwd)"
    docker compose run --rm --no-deps --entrypoint sh \
      -v "$BACKUP_ABS:/backup:ro" -v "$TARGET_ABS:/restore" api \
      -c "tar -xzf /backup/storage/documents.tar.gz -C /restore"
    echo "Documents restored to $TARGET (not activated automatically)."
  fi
else
  if [ -z "$SOURCE_BUCKET" ]; then
    echo "No source bucket recorded; skipping documents." >&2
  else
    TARGET_BUCKET="${TARGET_BUCKET:-$SOURCE_BUCKET-restore}"
    DOCS_ABS="$(cd "$BACKUP_DIR/documents" && pwd)"
    docker compose --env-file .env run --rm --no-deps --entrypoint python \
      -v "$DOCS_ABS:/backup:ro" api \
      -m app.scripts.s3_sync upload --bucket "$TARGET_BUCKET" --source /backup --create-bucket
    echo "Documents restored to bucket $TARGET_BUCKET."
  fi
fi

echo "Restore verification complete. Point DATABASE_URL at $DATABASE to use it."
