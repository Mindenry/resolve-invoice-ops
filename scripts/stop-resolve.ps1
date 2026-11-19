# Stops both application layers by default. Volumes, databases, uploads and
# native data directories are preserved. Use -DockerOnly or -NativeOnly to scope.

[CmdletBinding()]
param(
    [switch]$DockerOnly,
    [switch]$NativeOnly,
    [switch]$StopDockerDesktop
)

$ErrorActionPreference = "Continue"
if (-not $NativeOnly) {
    & (Join-Path $PSScriptRoot "stop-docker.ps1") -StopDockerDesktop:$StopDockerDesktop
}
if (-not $DockerOnly) {
    & (Join-Path $PSScriptRoot "stop-native.ps1")
}
Write-Host "Stop complete. No volumes or data were removed." -ForegroundColor Green
