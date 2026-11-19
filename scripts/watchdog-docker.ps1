# Keeps Docker Desktop available for the RESOLVE primary deployment.
# Runs every minute from Task Scheduler. It only starts the engine if it is down
# and no intentional-stop sentinel exists; containers have restart policies.

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$LogDir = Join-Path $Root "var\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "docker-watchdog.log"
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
$Desktop = "C:\Program Files\Docker\Docker\Docker Desktop.exe"
$Sentinel = Join-Path $Root "var\docker-watchdog.disabled"

function Write-Log([string]$Message) {
    Add-Content -Path $Log -Value "$(Get-Date -Format o) $Message" -Encoding UTF8
}

if (Test-Path $Sentinel) { exit 0 }

$version = & $Docker info --format "{{.ServerVersion}}" 2>$null
if ($LASTEXITCODE -eq 0 -and $version -match "^\d+\.\d+") { exit 0 }

Write-Log "Docker engine unavailable; starting Docker Desktop through Explorer."
Start-Process explorer.exe -ArgumentList "`"$Desktop`"" | Out-Null

for ($i = 1; $i -le 48; $i++) {
    Start-Sleep -Seconds 5
    $version = & $Docker info --format "{{.ServerVersion}}" 2>$null
    if ($LASTEXITCODE -eq 0 -and $version -match "^\d+\.\d+") {
        Write-Log "Docker engine ready ($version)."
        $required = @("api", "web", "postgres", "redis", "seaweedfs", "worker", "beat", "mailpit")
        $missing = @()
        foreach ($service in $required) {
            $id = & $Docker compose ps -q $service 2>$null
            if (-not $id) { $missing += $service }
        }
        if ($missing.Count -eq 0) {
            Write-Log "Compose containers already running; no action."
            exit 0
        }
        Write-Log "Starting missing Compose services: $($missing -join ', ')"
        Push-Location $Root
        try {
            & $Docker compose --env-file .env --profile monitoring up -d 2>&1 |
                ForEach-Object { Write-Log "compose: $_" }
        } finally {
            Pop-Location
        }
        exit 0
    }
}
Write-Log "Docker engine did not recover within 4 minutes."
exit 1
