# Backup RESOLVE PostgreSQL, local document storage and configuration.
# Secrets are copied into a restricted folder and never printed.

[CmdletBinding()]
param(
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Destination) { $Destination = Join-Path $Root "backups" }
$Stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$BackupDir = Join-Path $Destination "resolve-$Stamp"
$ApiDir = Join-Path $Root "apps\api"
$PgBin = "C:\Program Files\PostgreSQL\18\bin"

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $BackupDir "documents") | Out-Null

$envFile = Join-Path $ApiDir ".env"
$databaseUrl = (Get-Content $envFile | Where-Object { $_ -match "^DATABASE_URL=" } | Select-Object -First 1) -replace "^DATABASE_URL=", ""
if (-not $databaseUrl) { throw "DATABASE_URL not found in $envFile" }
$match = [regex]::Match($databaseUrl, "postgresql\+psycopg://(?<user>[^:@/]+)@(?<host>[^:/]+):(?<port>\d+)/(?<db>[^?]+)")
if (-not $match.Success) { throw "Unsupported DATABASE_URL format for backup." }
$dbHost = $match.Groups["host"].Value
$dbPort = $match.Groups["port"].Value
$dbUser = $match.Groups["user"].Value
$dbName = $match.Groups["db"].Value

Write-Host "Backing up database $dbName..." -ForegroundColor Cyan
$dump = Join-Path $BackupDir "database.dump"
& "$PgBin\pg_dump.exe" -h $dbHost -p $dbPort -U $dbUser -d $dbName -Fc -f $dump
if ($LASTEXITCODE -ne 0) { throw "pg_dump failed with exit code $LASTEXITCODE" }
& "$PgBin\pg_restore.exe" --list $dump > (Join-Path $BackupDir "database.toc.txt")
if ($LASTEXITCODE -ne 0) { throw "pg_restore --list failed; backup is not readable." }

$storageDir = $null
$storageLine = Get-Content $envFile | Where-Object { $_ -match "^STORAGE_LOCAL_DIR=" } | Select-Object -First 1
if ($storageLine) { $storageDir = ($storageLine -split "=", 2)[1].Trim() }
if ($storageDir -and (Test-Path $storageDir)) {
    Write-Host "Copying document storage..." -ForegroundColor Cyan
    Copy-Item -Path (Join-Path $storageDir "*") -Destination (Join-Path $BackupDir "documents") -Recurse -Force -ErrorAction SilentlyContinue
    $files = Get-ChildItem (Join-Path $BackupDir "documents") -Recurse -File -ErrorAction SilentlyContinue
    "Local storage copied from $storageDir ($($files.Count) files, $([math]::Round((($files | Measure-Object Length -Sum).Sum)/1MB,2)) MB)" |
        Set-Content (Join-Path $BackupDir "documents\README.txt")
} else {
    "No local storage directory configured or found. Back up object storage separately." |
        Set-Content (Join-Path $BackupDir "documents\README.txt")
}

Write-Host "Copying configuration..." -ForegroundColor Cyan
Copy-Item $envFile (Join-Path $BackupDir "api.env") -Force
$rootEnv = Join-Path $Root ".env"
if (Test-Path $rootEnv) { Copy-Item $rootEnv (Join-Path $BackupDir "compose.env") -Force }

# Secrets: only local Administrators/SYSTEM may read the backup.
& icacls $BackupDir /inheritance:r /grant:r "Administrators:(OI)(CI)F" "SYSTEM:(OI)(CI)F" | Out-Null

$counts = & "$PgBin\psql.exe" -h $dbHost -p $dbPort -U $dbUser -d $dbName -t -A -F "=" -c @"
select 'organizations', count(*) from organizations
union all select 'users', count(*) from users
union all select 'vendors', count(*) from vendors
union all select 'purchase_orders', count(*) from purchase_orders
union all select 'invoices', count(*) from invoices
union all select 'documents', count(*) from documents
union all select 'cases', count(*) from cases
union all select 'exceptions', count(*) from exceptions
union all select 'investigation_evidence', count(*) from investigation_evidence
union all select 'audit_logs', count(*) from audit_logs
union all select 'document_chunks', count(*) from document_chunks
union all select 'chunk_vectors', count(embedding_vec) from document_chunks;
"@

$hash = (Get-FileHash $dump -Algorithm SHA256).Hash
$manifest = [ordered]@{
    created_at = (Get-Date).ToString("o")
    database = $dbName
    host = "$dbHost`:$dbPort"
    dump_sha256 = $hash
    storage_source = $storageDir
    row_counts = @{}
    restore_note = "Restore requires the same CREDENTIAL_ENCRYPTION_KEY from api.env to decrypt integration credentials."
}
foreach ($line in $counts) {
    if ($line -match "^(?<key>[^=]+)=(?<value>.+)$") {
        $manifest.row_counts[$matches["key"]] = [int]$matches["value"]
    }
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content (Join-Path $BackupDir "manifest.json") -Encoding UTF8

Write-Host "Backup complete: $BackupDir" -ForegroundColor Green
Write-Host "  database.dump sha256=$hash"
Write-Host "  row counts and TOC written next to the dump."
Write-Host "  Keep api.env / CREDENTIAL_ENCRYPTION_KEY safe: encrypted credentials cannot be decrypted without it."
