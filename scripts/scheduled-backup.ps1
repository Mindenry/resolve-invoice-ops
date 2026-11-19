# Daily backup wrapper used by the RESOLVE-Daily-Backup scheduled task.
# Runs the Docker-first backup and appends a timestamped log line. It never
# deletes old backups; retention is a manual, reviewed operation.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "var\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "scheduled-backup.log"

function Write-Log([string]$Message) {
    Add-Content -Path $Log -Value "$(Get-Date -Format o) $Message" -Encoding UTF8
}

Push-Location $Root
try {
    Write-Log "Starting scheduled backup."
    $childLog = Join-Path $LogDir "scheduled-backup.last-run.log"
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "backup-resolve.ps1") *> $childLog
    $code = $LASTEXITCODE
    Get-Content $childLog -ErrorAction SilentlyContinue | ForEach-Object { Write-Log "backup: $_" }
    if ($code -ne 0) {
        Write-Log "Backup failed with exit code $code."
        exit $code
    }
    Write-Log "Backup completed."
    exit 0
} catch {
    Write-Log "Backup failed: $_"
    exit 1
} finally {
    Pop-Location
}
