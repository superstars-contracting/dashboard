@echo off
title Superstars - NYC Compliance Pull

cd /d "%~dp0"

echo ============================================================
echo   NYC COMPLIANCE WATCH - Live Data Pull
echo   Pulling permits, violations, and complaints for all
echo   active projects from NYC OpenData / DOB BIS.
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not installed. Install from python.org with "Add to PATH" checked.
    pause
    exit /b 1
)

REM Ensure schema migration has run
python apply_compliance_schema.py
if errorlevel 1 (
    echo.
    echo Schema migration failed. Stopping.
    pause
    exit /b 1
)

echo.
echo --- Pulling data for all projects ---
echo.

python nyc_compliance.py refresh-all

echo.
echo ============================================================
echo   Pulse log (last 15 runs):
echo ============================================================
python nyc_compliance.py status

echo.
pause
