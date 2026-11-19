# Reports both deployments; Docker Compose is the primary LAN deployment.

$ErrorActionPreference = "Continue"
Write-Host "================ DOCKER (PRIMARY) ================" -ForegroundColor White
& (Join-Path $PSScriptRoot "status-docker.ps1")
Write-Host ""
Write-Host "================ NATIVE (ROLLBACK, LOCALHOST) =====" -ForegroundColor White
& (Join-Path $PSScriptRoot "status-native.ps1")
