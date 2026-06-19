@echo off
setlocal
cd /d "%~dp0"

python scripts\build_windows_release.py %*
if errorlevel 1 (
  echo.
  echo [ERROR] Windows release build failed.
  exit /b 1
)

echo.
echo [INFO] Windows release build completed.
