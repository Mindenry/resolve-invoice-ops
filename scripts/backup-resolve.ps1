# Backs up the primary Docker Compose deployment by default. Use -Native for the
# native Windows deployment. Never deletes data; backup folders are ACL-restricted.

[CmdletBinding()]
param(
    [switch]$Native,
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if ($Native) {
    $args = @{}
    if ($Destination) { $args.Destination = $Destination }
    & (Join-Path $PSScriptRoot "backup-native.ps1") @args
    exit $LASTEXITCODE
}

$backupArgs = @{ StorageBackend = "s3" }
if ($Destination) { $backupArgs.Destination = $Destination }
& (Join-Path $Root "infrastructure\scripts\backup.ps1") @backupArgs
exit $LASTEXITCODE
