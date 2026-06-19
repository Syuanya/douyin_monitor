@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

if not exist ".env" copy /Y ".env.example" ".env" >nul

if exist ".venv\Scripts\python.exe" (
  set "PY_CMD=.venv\Scripts\python.exe"
) else (
  set "PY_CMD=python"
)

echo [INFO] Starting Douyin Monitor ...
echo [INFO] Python command: %PY_CMD%
set "PLATFORM=desktop"
set "PYTHONDONTWRITEBYTECODE=1"
%PY_CMD% main.py %*
if errorlevel 1 goto fail
exit /b 0

:fail
echo.
echo [ERROR] Douyin Monitor failed to start. Check the error output above.
pause
exit /b 1
