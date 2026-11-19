# Restore a RESOLVE backup into a NEW database (default) without touching live data.
# Use -Database resolve_live -Force only when you deliberately want to replace the live DB.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [string]$Database,
    [string]$StorageTarget,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$ApiDir = Join-Path $Root "apps\api"
$PgBin = "C:\Program Files\PostgreSQL\18\bin"
$PgHost = "127.0.0.1"
$PgPort = "55432"
$PgUser = "resolve"

if (-not (Test-Path (Join-Path $BackupDir "database.dump"))) {
    throw "database.dump not found in $BackupDir"
}
$manifest = Get-Content (Join-Path $BackupDir "manifest.json") -Raw | ConvertFrom-Json
if (-not $Database) {
    $Database = "resolve_live_restore_" + (Get-Date -Format "yyyyMMdd_HHmmss")
}
if ($Database -eq "resolve_live" -and -not $Force) {
    throw "Refusing to overwrite the live database. Pass -Force only after stopping RESOLVE and taking a fresh backup."
}

$exists = & "$PgBin\psql.exe" -h $PgHost -p $PgPort -U $PgUser -d postgres -t -A -c "select 1 from pg_database where datname='$Database'"
if ("$exists".Trim() -eq "1") {
    if (-not $Force) { throw "Database $Database already exists. Choose another name or pass -Force." }
    Write-Host "Dropping existing database $Database (explicit -Force)..." -ForegroundColor Yellow
    & "$PgBin\dropdb.exe" -h $PgHost -p $PgPort -U $PgUser $Database
}
& "$PgBin\createdb.exe" -h $PgHost -p $PgPort -U $PgUser $Database
if ($LASTEXITCODE -ne 0) { throw "createdb failed" }

Write-Host "Restoring into $Database ..." -ForegroundColor Cyan
& "$PgBin\pg_restore.exe" -h $PgHost -p $PgPort -U $PgUser -d $Database --no-owner --no-privileges (Join-Path $BackupDir "database.dump")
if ($LASTEXITCODE -ne 0) { throw "pg_restore failed with exit code $LASTEXITCODE" }

$verify = & "$PgBin\psql.exe" -h $PgHost -p $PgPort -U $PgUser -d $Database -t -A -F "=" -c @"
select 'organizations', count(*) from organizations
union all select 'invoices', count(*) from invoices
union all select 'documents', count(*) from documents
union all select 'cases', count(*) from cases
union all select 'audit_logs', count(*) from audit_logs
union all select 'document_chunks', count(*) from document_chunks
union all select 'chunk_vectors', count(embedding_vec) from document_chunks;
"@
Write-Host "Restored row counts:" -ForegroundColor Green
$verify | ForEach-Object { Write-Host "  $_" }

if ($StorageTarget) {
    if (Test-Path $StorageTarget) { throw "Storage target already exists: $StorageTarget" }
    New-Item -ItemType Directory -Force -Path $StorageTarget | Out-Null
    Copy-Item (Join-Path $BackupDir "documents\*") $StorageTarget -Recurse -Force
    Write-Host "Documents restored to $StorageTarget (not activated automatically)." -ForegroundColor Green
}

Write-Host ""
Write-Host "Restore verification complete." -ForegroundColor Green
Write-Host "To use this database, set DATABASE_URL in apps/api/.env to:"
Write-Host "  postgresql+psycopg://resolve@${PgHost}:${PgPort}/$Database"
Write-Host "Keep the original CREDENTIAL_ENCRYPTION_KEY from api.env if you restore integration credentials."
