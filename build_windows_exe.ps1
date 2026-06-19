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

Write-Host "[INFO] Building Windows executable..."
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --name DouyinMonitor `
    --windowed `
    --add-data "assets;assets" `
    --add-data "locales;locales" `
    --add-data "config/default_settings.json;config" `
    --add-data "config/language.json;config" `
    main.py

Write-Host "[INFO] Build completed: dist/DouyinMonitor"
