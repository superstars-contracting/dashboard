@echo off
title Superstars - Seed Sample Workers

cd /d "%~dp0"

echo.
echo ============================================================
echo   CREATING SAMPLE WORKERS WITH SAMPLE CERTS
echo ============================================================
echo.
echo   Will create 5 fake workers with realistic NYC certs.
echo   Server must be running (run_server.bat).
echo.
echo   Press any key to start, or close this window to cancel.
pause >nul

echo.
python create_sample_workers.py

echo.
pause
