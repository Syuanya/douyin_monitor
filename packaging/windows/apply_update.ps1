param(
    [Parameter(Mandatory=$true)][string]$InstallerPath,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $InstallerPath)) {
    throw "Installer not found: $InstallerPath"
}
$argsList = @()
if ($Silent) {
    $argsList += "/VERYSILENT"
    $argsList += "/NORESTART"
    $argsList += "/CLOSEAPPLICATIONS"
} else {
    $argsList += "/CLOSEAPPLICATIONS"
}
Start-Process -FilePath $InstallerPath -ArgumentList $argsList -WorkingDirectory (Split-Path -Parent $InstallerPath)
