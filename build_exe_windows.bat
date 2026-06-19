@echo off
setlocal EnableExtensions
cd /d "%~dp0"

set "PYTHON_CMD=python"
where python >nul 2>nul
if errorlevel 1 (
  where py >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python not found. Please install Python 3.10-3.12 and add it to PATH.
    goto :fail
  )
  set "PYTHON_CMD=py -3"
)

if not exist ".venv\Scripts\python.exe" (
  echo [INFO] Creating virtual environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :fail
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :fail

echo [INFO] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail

echo [INFO] Installing project dependencies...
python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

echo [INFO] Installing PyInstaller...
python -m pip install pyinstaller
if errorlevel 1 goto :fail

echo [INFO] Checking runtime...
python scripts\check_runtime.py
if errorlevel 1 goto :fail

echo [INFO] Building Windows executable...
python -m PyInstaller packaging\windows\douyin_monitor.spec --noconfirm --clean
if errorlevel 1 goto :fail

echo.
echo [SUCCESS] Build completed.
echo [OUTPUT] dist\DouyinMonitor\DouyinMonitor.exe
goto :done

:fail
echo.
echo [ERROR] Build failed. Please check the messages above.
if /I not "%~1"=="--no-pause" pause
exit /b 1

:done
if /I not "%~1"=="--no-pause" pause
exit /b 0
