@echo off
title Superstars - Apply All Schema Migrations

cd /d "%~dp0"

echo ============================================================
echo   APPLYING ALL SCHEMA MIGRATIONS (idempotent — safe to re-run)
echo ============================================================
echo.

echo --- CoF schema ---
python apply_cof_schema.py
echo.
echo --- Worker Intake schema + cert library ---
python apply_worker_intake_schema.py
echo.
echo --- Project assignments schema ---
python apply_assignments_schema.py
echo.
echo --- NYC Compliance schema (in case not yet applied) ---
python apply_compliance_schema.py 2>nul
echo.
echo ============================================================
echo   ALL MIGRATIONS DONE
echo.
echo   Now RESTART the server:
echo     1. Close the run_server.bat window (Ctrl+C)
echo     2. Double-click run_server.bat
echo.
echo   Then seed sample data:
echo     1. Double-click seed_sample_workers.bat
echo ============================================================
echo.
pause
