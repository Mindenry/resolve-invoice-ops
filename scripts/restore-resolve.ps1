# Restores a Docker Compose backup into a NEW database by default. Use -Native
# for the native deployment. Never overwrites live data without -Force.

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$BackupDir,
    [string]$Database,
    [string]$TargetBucket,
    [switch]$Force,
    [switch]$Native,
    [string]$StorageTarget
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot

if ($Native) {
    $args = @{ BackupDir = $BackupDir }
    if ($Database) { $args.Database = $Database }
    if ($StorageTarget) { $args.StorageTarget = $StorageTarget }
    if ($Force) { $args.Force = $true }
    & (Join-Path $PSScriptRoot "restore-native.ps1") @args
    exit $LASTEXITCODE
}

$restoreArgs = @{ BackupDir = $BackupDir }
if ($Database) { $restoreArgs.Database = $Database }
if ($TargetBucket) { $restoreArgs.TargetBucket = $TargetBucket }
if ($Force) { $restoreArgs.Force = $true }
& (Join-Path $Root "infrastructure\scripts\restore.ps1") @restoreArgs
exit $LASTEXITCODE
