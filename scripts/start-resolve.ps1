# Primary RESOLVE start command.
# Auto mode prefers the Docker Compose deployment and falls back to the verified
# native Windows services if Docker is unavailable.

[CmdletBinding()]
param(
    [ValidateSet("auto", "docker", "native")]
    [string]$Mode = "auto",
    [switch]$SkipMigrations,
    [switch]$NoRestart
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if ($Mode -in @("auto", "docker")) {
    try {
        & (Join-Path $PSScriptRoot "start-docker.ps1")
        if ($LASTEXITCODE -eq 0) { exit 0 }
        Write-Warning "Docker start did not report healthy (exit $LASTEXITCODE)."
    } catch {
        Write-Warning "Docker deployment unavailable: $($_.Exception.Message)"
    }
    if ($Mode -eq "docker") { exit 1 }
    Write-Host "Falling back to the native Windows deployment..." -ForegroundColor Yellow
}

$nativeArgs = @{}
if ($SkipMigrations) { $nativeArgs.SkipMigrations = $true }
if ($NoRestart) { $nativeArgs.NoRestart = $true }
& (Join-Path $PSScriptRoot "start-native.ps1") @nativeArgs
exit $LASTEXITCODE
