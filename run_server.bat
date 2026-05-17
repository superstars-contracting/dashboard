@echo off
title Superstars PM Server (Local)

cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not installed. Install from python.org with "Add to PATH" checked.
    pause
    exit /b 1
)

echo Installing required packages (one-time)...
python -m pip install flask flask-cors --quiet --upgrade 2>nul

echo.
echo Killing any old Python processes that might block the port...
taskkill /F /IM python.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo.
echo ============================================================
echo   SUPERSTARS PROJECT CONSOLE
echo   Local server starting at http://localhost:5050
echo   Open this URL in Chrome or Safari:
echo     http://localhost:5050
echo   Press Ctrl+C in this window to stop the server.
echo ============================================================
echo.

python server.py
pause
