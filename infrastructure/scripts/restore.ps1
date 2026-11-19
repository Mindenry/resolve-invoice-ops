# Restore a Docker Compose backup into a NEW database by default.
# Documents are restored to a separate bucket/directory unless overridden.
[CmdletBinding()]
param(
  [Parameter(Mandatory = $true)][string]$BackupDir,
  [string]$Database,
  [string]$TargetBucket,
  [switch]$Force
)

$ErrorActionPreference = "Stop"

function Get-DotEnvValue([string]$Key) {
  $line = Get-Content ".env" -ErrorAction SilentlyContinue |
    Where-Object { $_ -match "^$([regex]::Escape($Key))=" } |
    Select-Object -First 1
  if ($line) { return ($line -split "=", 2)[1].Trim() }
  return $null
}

if (-not (Test-Path (Join-Path $BackupDir "database.dump"))) {
  throw "database.dump not found in $BackupDir"
}
if (-not $Database) {
  $Database = "resolve_restore_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ($Database -notmatch "^[A-Za-z0-9_]+$") { throw "Invalid database name: $Database" }

$manifest = Get-Content (Join-Path $BackupDir "manifest.json") -Raw | ConvertFrom-Json
$PostgresUser = if ($env:POSTGRES_USER) { $env:POSTGRES_USER } else { Get-DotEnvValue "POSTGRES_USER" }
if (-not $PostgresUser) { $PostgresUser = "resolve" }

$exists = docker compose exec -T postgres psql -U $PostgresUser -d postgres -t -A -c "select 1 from pg_database where datname='$Database'"
if ("$exists".Trim() -eq "1") {
  if (-not $Force) { throw "Database $Database already exists. Choose another name or pass -Force." }
  docker compose exec -T postgres psql -U $PostgresUser -d postgres -c "DROP DATABASE $Database"
}

Write-Host "Restoring database into $Database..." -ForegroundColor Cyan
docker compose exec -T postgres psql -U $PostgresUser -d postgres -c "CREATE DATABASE $Database"
$dumpFile = (Resolve-Path (Join-Path $BackupDir "database.dump")).Path
docker compose cp $dumpFile "postgres:/tmp/resolve-restore.dump"
docker compose exec -T postgres pg_restore -U $PostgresUser -d $Database --no-owner --no-privileges /tmp/resolve-restore.dump
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed" }
docker compose exec -T postgres rm -f /tmp/resolve-restore.dump | Out-Null

Write-Host "Verifying restored rows..." -ForegroundColor Cyan
docker compose exec -T postgres psql -U $PostgresUser -d $Database -t -A -F "=" -c @"
select 'organizations', count(*) from organizations
union all select 'invoices', count(*) from invoices
union all select 'documents', count(*) from documents
union all select 'cases', count(*) from cases
union all select 'audit_logs', count(*) from audit_logs
union all select 'document_chunks', count(*) from document_chunks;
"@

$Backend = $manifest.storage_backend
if (-not $Backend) { $Backend = "s3" }
if ($Backend -eq "local") {
  $archive = Join-Path $BackupDir "storage\documents.tar.gz"
  if (-not (Test-Path $archive)) {
    Write-Host "No local document archive found; skipping documents." -ForegroundColor Yellow
  } else {
    $Target = Join-Path $BackupDir "restored-storage"
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    $BackupAbs = (Resolve-Path $BackupDir).Path
    $TargetAbs = (Resolve-Path $Target).Path
    docker compose run --rm --no-deps --entrypoint sh `
      -v "$BackupAbs`:/backup:ro" -v "$TargetAbs`:/restore" api `
      -c "tar -xzf /backup/storage/documents.tar.gz -C /restore"
    Write-Host "Documents restored to $Target (not activated automatically)." -ForegroundColor Green
  }
} else {
  $SourceBucket = $manifest.bucket
  if (-not $SourceBucket) {
    Write-Host "No source bucket recorded; skipping documents." -ForegroundColor Yellow
  } else {
    if (-not $TargetBucket) { $TargetBucket = "$SourceBucket-restore" }
    $DocsAbs = (Resolve-Path (Join-Path $BackupDir "documents")).Path
    # Docker Compose writes progress to stderr; keep it from terminating the
    # script under $ErrorActionPreference = "Stop".
    $ErrorActionPreference = "Continue"
    docker compose run --rm --no-deps --entrypoint python -v "$DocsAbs`:/backup:ro" api `
      -m app.scripts.s3_sync upload --bucket $TargetBucket --source /backup --create-bucket
    $syncExit = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
    if ($syncExit -ne 0) { throw "document restore sync failed" }
    Write-Host "Documents restored to bucket $TargetBucket." -ForegroundColor Green
  }
}

Write-Host "Restore verification complete. Point DATABASE_URL at $Database to use it." -ForegroundColor Green
