@echo off
setlocal enabledelayedexpansion
title Superstars Contracting - RFI Email Sender

echo.
echo ===============================================================
echo   SUPERSTARS CONTRACTING
echo   RFI Email Sender - Live Test
echo ===============================================================
echo.

REM Ensure we run from the folder where this .bat file lives
cd /d "%~dp0"

REM Step 1: Check Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo [X] Python is not installed on this computer.
    echo.
    echo To install:
    echo   1. Open a browser and go to: https://python.org/downloads
    echo   2. Click "Download Python 3.12" or newer
    echo   3. Run the downloaded installer
    echo   4. IMPORTANT: Check the box "Add Python to PATH" during install
    echo   5. Finish install, then run this batch file again
    echo.
    echo Press any key to close...
    pause >nul
    exit /b 1
)

echo [OK] Python found.
echo.

REM Step 2: Install / update sendgrid library
echo Installing email library (one-time, may take 30 seconds)...
python -m pip install sendgrid --quiet --upgrade 2>nul
if errorlevel 1 (
    echo [X] Failed to install sendgrid library.
    echo Try opening Command Prompt manually and running:
    echo   pip install sendgrid
    echo.
    pause
    exit /b 1
)
echo [OK] Email library ready.
echo.

REM Step 3: Run the actual sender script
echo Running RFI email sender...
echo ---------------------------------------------------------------
python send_rfi_emails.py
set EXITCODE=%errorlevel%
echo ---------------------------------------------------------------
echo.

if %EXITCODE%==0 (
    echo [OK] Done. Check your inbox at the DEV_EMAIL_OVERRIDE address.
) else (
    echo [X] Something went wrong. See the messages above.
)

echo.
echo Press any key to close...
pause >nul
