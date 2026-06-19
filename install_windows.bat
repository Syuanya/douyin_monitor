@echo off
chcp 65001 >nul
setlocal EnableExtensions
cd /d "%~dp0"

set "PY_CMD="
for %%C in ("py -3.11" "py -3.12" "py -3.10" "python") do (
  call %%~C -c "import sys,platform; raise SystemExit(0 if (3,10) <= sys.version_info < (4,0) and platform.architecture()[0]=='64bit' else 1)" >nul 2>nul
  if not errorlevel 1 (
    if not defined PY_CMD set "PY_CMD=%%~C"
  )
)

if not defined PY_CMD (
  echo [ERROR] No compatible Python was found. Required: Python 3.10+ x64.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating virtual environment ...
  %PY_CMD% -m venv .venv
  if errorlevel 1 goto fail
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto fail

set "PYTHONDONTWRITEBYTECODE=1"
python -m pip install --upgrade pip setuptools wheel
if errorlevel 1 goto fail
python -m pip install -r requirements.txt
if errorlevel 1 goto fail

echo [INFO] Install complete. Run run_windows.bat to start.
pause
exit /b 0

:fail
echo.
echo [ERROR] Install failed. Check the error output above.
pause
exit /b 1
