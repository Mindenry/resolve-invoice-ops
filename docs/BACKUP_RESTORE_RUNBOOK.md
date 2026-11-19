# Backup and restore runbook

Backups contain database dumps, uploaded documents and configuration/encryption-key material. They
must be protected and stored off-host. Never commit them to Git.

## 1. Docker (primary)

### Backup

```powershell
cd "C:\path\to\resolve"
.\scripts\backup-resolve.ps1                 # delegates to infrastructure/scripts/backup.ps1 -StorageBackend s3

# or directly
powershell -NoProfile -ExecutionPolicy Bypass -File .\infrastructure\scripts\backup.ps1 -StorageBackend s3
```

Output: `backups/compose-YYYYMMDD-HHMMSS/`

- `database.dump` — PostgreSQL custom format
- `database.toc.txt` — readable `pg_restore --list`
- `documents/` — mirror of the S3 bucket
- `manifest.json` — row counts, dump SHA-256, storage backend/bucket
- secrets are **not** printed; keep `api.env`/root `.env` access restricted

### Restore into a separate database (default)

```powershell
.\scripts\restore-resolve.ps1 -BackupDir .\backups\compose-YYYYMMDD-HHMMSS
```

The restore script:

1. Creates a new database `resolve_restore_<timestamp>` (never overwrites live without `-Force`).
2. Runs `pg_restore --no-owner --no-privileges`.
3. Verifies organizations, invoices, documents, cases, audit logs and chunks.
4. Uploads documents to a new bucket (`resolve-documents-restore` by default).

To activate a verified restore, change `DATABASE_URL`/`S3_BUCKET` in `.env`, restart the stack, and
keep the old database/bucket untouched until acceptance.

### Verified restore on this host

- Backup: `backups/compose-20261119-184900`
- Restored DB: `resolve_restore_final`
- Rows: organizations=1, invoices=103, documents=11, cases=38, audit_logs=497, chunks=11
- pgvector 0.8.7, `vector(1024)`, HNSW index, 11/11 vectors
- Documents: 42 objects restored to `resolve-documents-final`; 42/42 SHA-256 hashes matched

## 2. Native Windows (rollback)

```powershell
.\scripts\backup-resolve.ps1 -Native
.\scripts\restore-resolve.ps1 -Native -BackupDir .\backups\resolve-YYYYMMDD-HHMMSS
```

Native backup contains `database.dump`, local storage copy, `api.env`, `compose.env`, `manifest.json`.
Restore defaults to a new database (`resolve_live_restore_<timestamp>`) and refuses to overwrite
`resolve_live` without `-Force`.

Verified example: `backups/resolve-20261119-174236` restored to
`resolve_live_restore_20261119_174248` with 19 chunks and 19 vectors.

## 3. Encryption keys

Integration credentials are encrypted with a key derived from `CREDENTIAL_ENCRYPTION_KEY` or
`SECRET_KEY`. A database restore **without the original key** leaves integration credentials
undecryptable. Back up the configuration together with the database, but store it encrypted and
access-controlled.

Never rotate `SECRET_KEY`/`CREDENTIAL_ENCRYPTION_KEY` without a documented rotation plan; rotating
`SECRET_KEY` also invalidates existing sessions.

## 4. Restore drill rules

- Never restore over the live DB during verification.
- Verify row counts, `alembic_version`, pgvector extension/column/index and a sample document
  download.
- Keep the source backup until the restored environment passes login, upload, AI and approval checks.
- Test a restore quarterly and record the outcome.
- Backups contain personal/financial data; apply retention and deletion policy.

## 5. Verified evidence (2026-11-19)

**Backup:** `backups/compose-20261119-205946`

- Snapshot counts: 4 organizations, 9 users, 14 vendors, 23 purchase orders, 106 invoices,
  17 documents, 48 cases, 149 exceptions, 741 audit rows, 16 chunks, **65 S3 objects**.
- `manifest.json` records the dump SHA-256.

**Restore:** database `resolve_restore_hardening_20261119_210117`, bucket
`resolve-documents-restore-hardening`.

- Row counts, 16 vector rows at dimension **1024**, index `ix_document_chunks_embedding_vec` (HNSW)
  and a nearest-neighbour query were verified.
- 65 objects were uploaded; one object's SHA-256 matched the backup mirror byte-for-byte.
- The live database was not overwritten.

**Backup freshness metric:** each successful run writes
`var/metrics/resolve_backup.prom` (LF endings), collected by node-exporter as
`resolve_backup_last_success_timestamp_seconds`. The `ResolveBackupStale` alert fires when no backup
has succeeded for 26 hours.
