param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host "[INFO] Checking runtime..."
& $Python scripts/check_runtime.py

Write-Host "[INFO] Installing PyInstaller if missing..."
& $Python -m pip show pyinstaller *> $null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install pyinstaller
}

Write-Host "[INFO] Building Windows executable with shared PyInstaller spec..."
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    packaging/windows/douyin_monitor.spec

Write-Host "[INFO] Build completed: dist/DouyinMonitor"
