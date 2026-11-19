# Backup the Docker Compose stack (PostgreSQL + object storage).
# Run from the repository root. Secrets are read from .env and never printed.
[CmdletBinding()]
param(
  [string]$Destination = ".\backups",
  [ValidateSet("s3", "local")]
  [string]$StorageBackend
)

$ErrorActionPreference = "Stop"

function Get-DotEnvValue([string]$Key) {
  $line = Get-Content ".env" -ErrorAction SilentlyContinue |
    Where-Object { $_ -match "^$([regex]::Escape($Key))=" } |
    Select-Object -First 1
  if ($line) { return ($line -split "=", 2)[1].Trim() }
  return $null
}

$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$PostgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { Get-DotEnvValue "POSTGRES_USER" }
if (-not $PostgresUser) { $PostgresUser = "resolve" }
$PostgresDb = if ($env:POSTGRES_DB) { $env:POSTGRES_DB } else { Get-DotEnvValue "POSTGRES_DB" }
if (-not $PostgresDb) { $PostgresDb = "resolve" }
$Bucket = if ($env:S3_BUCKET) { $env:S3_BUCKET } else { Get-DotEnvValue "S3_BUCKET" }
if (-not $Bucket) { $Bucket = "resolve-documents" }
$Backend = if ($StorageBackend) { $StorageBackend }
  elseif ($env:STORAGE_BACKEND) { $env:STORAGE_BACKEND }
  else { Get-DotEnvValue "STORAGE_BACKEND" }
if (-not $Backend) { $Backend = "s3" }

$BackupDir = Join-Path $Destination "compose-$Stamp"
New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
$BackupDir = (Resolve-Path $BackupDir).Path

Write-Host "Backing up database $PostgresDb..." -ForegroundColor Cyan
docker compose exec -T postgres pg_dump -U $PostgresUser -d $PostgresDb -Fc -f /tmp/resolve-backup.dump
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed" }

$dumpFile = Join-Path $BackupDir "database.dump"
docker compose cp "postgres:/tmp/resolve-backup.dump" $dumpFile
if ($LASTEXITCODE -ne 0) { throw "could not copy the database dump out of the container" }

docker compose exec -T postgres pg_restore --list /tmp/resolve-backup.dump |
  Set-Content (Join-Path $BackupDir "database.toc.txt")
docker compose exec -T postgres rm -f /tmp/resolve-backup.dump | Out-Null

if ($Backend -eq "local") {
  Write-Host "Backing up local storage volume..." -ForegroundColor Cyan
  $StorageDir = Join-Path $BackupDir "storage"
  New-Item -ItemType Directory -Force -Path $StorageDir | Out-Null
  $Mount = "$StorageDir`:/backup"
  docker compose run --rm --no-deps --entrypoint sh -v $Mount api `
    -c "tar -czf /backup/documents.tar.gz -C /app/var/storage ."
  if ($LASTEXITCODE -ne 0) { throw "local storage archive failed" }
} else {
  Write-Host "Backing up object storage bucket $Bucket..." -ForegroundColor Cyan
  $DocumentsDir = (Join-Path $BackupDir "documents")
  New-Item -ItemType Directory -Force -Path $DocumentsDir | Out-Null
  $Mount = "$DocumentsDir`:/backup"
  docker compose run --rm --no-deps --entrypoint python -v $Mount api `
    -m app.scripts.s3_sync download --bucket $Bucket --dest /backup --delete
  if ($LASTEXITCODE -ne 0) { throw "object storage mirror failed" }
}

Write-Host "Collecting verification counts..." -ForegroundColor Cyan
$counts = docker compose exec -T postgres psql -U $PostgresUser -d $PostgresDb -t -A -F "=" -c @"
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
"@
if ($LASTEXITCODE -ne 0) { throw "post-backup count query failed" }

$manifest = [ordered]@{
  created_at = (Get-Date).ToString("o")
  database = $PostgresDb
  storage_backend = $Backend
  bucket = if ($Backend -eq "s3") { $Bucket } else { $null }
  dump_sha256 = (Get-FileHash $dumpFile -Algorithm SHA256).Hash
  row_counts = @{}
  restore_note = "Restore with infrastructure/scripts/restore.ps1. Keep the same CREDENTIAL_ENCRYPTION_KEY (or SECRET_KEY) to decrypt integration credentials."
}
foreach ($line in $counts) {
  if ($line -match "^(?<key>[^=]+)=(?<value>.+)$") {
    $manifest.row_counts[$matches["key"]] = [int]$matches["value"]
  }
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $BackupDir "manifest.json") -Encoding UTF8

# Publish a host-side backup timestamp for Prometheus (node-exporter textfile collector).
try {
  $MetricsDir = Join-Path (Get-Location) "var\metrics"
  New-Item -ItemType Directory -Force -Path $MetricsDir | Out-Null
  $Epoch = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
  $Lines = @(
    "# HELP resolve_backup_last_success_timestamp_seconds Unix time of the last successful RESOLVE backup.",
    "# TYPE resolve_backup_last_success_timestamp_seconds gauge",
    "resolve_backup_last_success_timestamp_seconds $Epoch"
  ) -join "`n"
  # Write LF endings: the Prometheus text parser rejects CRLF in type lines.
  [System.IO.File]::WriteAllText(
    (Join-Path $MetricsDir "resolve_backup.prom"),
    $Lines + "`n",
    [System.Text.Encoding]::ASCII
  )
} catch {
  Write-Warning "Backup succeeded but the Prometheus backup metric could not be written: $_"
}

Write-Host "Backup complete: $BackupDir" -ForegroundColor Green
