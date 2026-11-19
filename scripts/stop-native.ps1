# Stops the RESOLVE application services. Infrastructure (PostgreSQL, Redis/Memurai)
# and all data directories remain untouched.

[CmdletBinding()]
param(
    [switch]$IncludeAuxiliary
)

$ErrorActionPreference = "Continue"
$services = @("RESOLVE-API", "RESOLVE-Worker", "RESOLVE-Beat", "RESOLVE-Web")
if ($IncludeAuxiliary) { $services += @("RESOLVE-Mailpit", "RESOLVE-Ollama") }

foreach ($name in $services) {
    $service = Get-Service -Name $name -ErrorAction SilentlyContinue
    if ($null -eq $service) { continue }
    if ($service.Status -eq "Running") {
        Write-Host "Stopping $name..." -ForegroundColor Cyan
        Stop-Service -Name $name -Force
        $service.WaitForStatus("Stopped", [TimeSpan]::FromSeconds(30))
    } else {
        Write-Host "$name is already $($service.Status)."
    }
}

Write-Host "RESOLVE application services stopped." -ForegroundColor Green
Write-Host "PostgreSQL, Redis and data volumes were not touched."
if (-not $IncludeAuxiliary) {
    Write-Host "Ollama and Mailpit are still running (use -IncludeAuxiliary to stop them)."
}
