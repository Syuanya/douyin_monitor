@echo off
setlocal
cd /d "%~dp0"
echo [INFO] Checking Douyin Monitor runtime ...
python scripts\check_runtime.py
if errorlevel 1 (
    echo.
    echo [ERROR] Runtime check failed. Install dependencies with install_windows.bat first.
    pause
    exit /b 1
)
echo [INFO] Starting Douyin Monitor ...
python main.py
if errorlevel 1 (
    echo.
    echo [ERROR] Douyin Monitor failed to start. Check the error output above.
    pause
    exit /b 1
)
