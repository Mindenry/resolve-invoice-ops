#!/usr/bin/env bash
# Backup the Docker Compose stack (PostgreSQL + object storage).
# Run from the repository root. Secrets are read from .env and never printed.
set -euo pipefail

envval() {
  grep -E "^$1=" .env 2>/dev/null | tail -n 1 | cut -d= -f2- | tr -d '\r'
}

DEST="${BACKUP_DIR:-./backups}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR_PATH="$DEST/compose-$STAMP"
POSTGRES_USER="${POSTGRES_USER:-$(envval POSTGRES_USER)}"
POSTGRES_USER="${POSTGRES_USER:-resolve}"
POSTGRES_DB="${POSTGRES_DB:-$(envval POSTGRES_DB)}"
POSTGRES_DB="${POSTGRES_DB:-resolve}"
BUCKET="${S3_BUCKET:-$(envval S3_BUCKET)}"
BUCKET="${BUCKET:-resolve-documents}"
BACKEND="${STORAGE_BACKEND:-$(envval STORAGE_BACKEND)}"
BACKEND="${BACKEND:-s3}"

mkdir -p "$BACKUP_DIR_PATH"

echo "Backing up database $POSTGRES_DB..."
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/resolve-backup.dump
docker compose cp postgres:/tmp/resolve-backup.dump "$BACKUP_DIR_PATH/database.dump"
docker compose exec -T postgres pg_restore --list /tmp/resolve-backup.dump > "$BACKUP_DIR_PATH/database.toc.txt"
docker compose exec -T postgres rm -f /tmp/resolve-backup.dump

if [ "$BACKEND" = "local" ]; then
  echo "Backing up local storage volume..."
  mkdir -p "$BACKUP_DIR_PATH/storage"
  STORAGE_ABS="$(cd "$BACKUP_DIR_PATH/storage" && pwd)"
  docker compose run --rm --no-deps --entrypoint sh -v "$STORAGE_ABS:/backup" api \
    -c "tar -czf /backup/documents.tar.gz -C /app/var/storage ."
else
  echo "Backing up object storage bucket $BUCKET..."
  mkdir -p "$BACKUP_DIR_PATH/documents"
  DOCS_ABS="$(cd "$BACKUP_DIR_PATH/documents" && pwd)"
  docker compose --env-file .env run --rm --no-deps --entrypoint python \
    -v "$DOCS_ABS:/backup" api \
    -m app.scripts.s3_sync download --bucket "$BUCKET" --dest /backup --delete
fi

echo "Collecting verification counts..."
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -t -A -F "=" -c "
select 'organizations', count(*) from organizations
union all select 'users', count(*) from users
union all select 'vendors', count(*) from vendors
union all select 'purchase_orders', count(*) from purchase_orders
union all select 'invoices', count(*) from invoices
union all select 'documents', count(*) from documents
union all select 'cases', count(*) from cases
union all select 'exceptions', count(*) from exceptions
union all select 'audit_logs', count(*) from audit_logs
union all select 'document_chunks', count(*) from document_chunks;
" > "$BACKUP_DIR_PATH/row-counts.txt"

DUMP_SHA="$(sha256sum "$BACKUP_DIR_PATH/database.dump" | cut -d' ' -f1)"
{
  echo "created_at=$(date -Iseconds)"
  echo "database=$POSTGRES_DB"
  echo "storage_backend=$BACKEND"
  echo "bucket=$([ "$BACKEND" = "s3" ] && echo "$BUCKET")"
  echo "dump_sha256=$DUMP_SHA"
  echo "restore_note=Restore with infrastructure/scripts/restore.sh. Keep the same CREDENTIAL_ENCRYPTION_KEY (or SECRET_KEY) to decrypt integration credentials."
} > "$BACKUP_DIR_PATH/manifest.env"
cat "$BACKUP_DIR_PATH/row-counts.txt" >> "$BACKUP_DIR_PATH/manifest.env"

echo "Backup complete: $BACKUP_DIR_PATH"
