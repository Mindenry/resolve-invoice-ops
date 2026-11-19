# Stops the Docker Compose application containers. Volumes (database, object
# storage, n8n, Grafana) are preserved. Docker Desktop itself is left running.

[CmdletBinding()]
param(
    [switch]$StopDockerDesktop
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $PSScriptRoot
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
Set-Location $Root

$version = & $Docker info --format "{{.ServerVersion}}" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Docker engine is not running; nothing to stop." -ForegroundColor Yellow
    exit 0
}

Write-Host "Stopping Compose containers (volumes preserved)..." -ForegroundColor Cyan
& $Docker compose --env-file .env --profile monitoring stop
if ($LASTEXITCODE -ne 0) { Write-Warning "docker compose stop returned $LASTEXITCODE" }

if ($StopDockerDesktop) {
    New-Item -ItemType File -Force -Path (Join-Path $Root "var\docker-watchdog.disabled") | Out-Null
    Write-Host "Stopping Docker Desktop..." -ForegroundColor Cyan
    Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
}
Write-Host "RESOLVE Docker containers stopped. Volumes were not removed." -ForegroundColor Green
