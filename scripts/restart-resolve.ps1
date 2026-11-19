# Restarts the active deployment without removing data.

[CmdletBinding()]
param(
    [ValidateSet("auto", "docker", "native")]
    [string]$Mode = "auto"
)

$ErrorActionPreference = "Continue"
if ($Mode -eq "native") {
    & (Join-Path $PSScriptRoot "stop-native.ps1")
    & (Join-Path $PSScriptRoot "start-native.ps1")
    exit $LASTEXITCODE
}

$docker = "C:\Program Files\Docker\Docker\resources\bin\docker.exe"
& $docker info --format "{{.ServerVersion}}" 2>$null | Out-Null
if ($LASTEXITCODE -eq 0 -or $Mode -eq "docker") {
    & (Join-Path $PSScriptRoot "restart-docker.ps1")
    exit $LASTEXITCODE
}

& (Join-Path $PSScriptRoot "start-resolve.ps1") -Mode auto
exit $LASTEXITCODE
