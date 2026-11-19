# Restarts the Docker Compose deployment without removing volumes.

[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
Set-Location $Root

$version = & $Docker info --format "{{.ServerVersion}}" 2>$null
if ($LASTEXITCODE -ne 0) {
    & (Join-Path $PSScriptRoot "start-docker.ps1")
    exit $LASTEXITCODE
}

Write-Host "Restarting Compose containers..." -ForegroundColor Cyan
& $Docker compose --env-file .env --profile monitoring restart
if ($LASTEXITCODE -ne 0) { throw "docker compose restart failed" }

for ($i = 1; $i -le 60; $i++) {
    try {
        $response = Invoke-WebRequest -Uri "https://127.0.0.1:8180/health" -UseBasicParsing -TimeoutSec 5
        if ($response.StatusCode -eq 200) {
            Write-Host "RESOLVE Docker deployment restarted and healthy." -ForegroundColor Green
            exit 0
        }
    } catch { }
    Start-Sleep -Seconds 3
}
throw "RESOLVE did not become healthy after restart."
