@echo off
title Superstars - Live Email Demo

cd /d "%~dp0"

echo.
echo ============================================================
echo   SUPERSTARS - LIVE EMAIL DEMO (SendGrid)
echo ============================================================
echo.
echo   Sending the 9 RFI workflow emails through SendGrid.
echo   LIVE_MODE = false (safe), so all 9 emails will arrive at:
echo     amit@superstarscontracting.com
echo.
echo   Emails will land in your inbox within ~30 seconds.
echo   Each email includes the RFI as an HTML body + PDF attachment.
echo.
echo ============================================================
echo.
echo   Press any key to send the batch, or close this window to cancel.
pause >nul

echo.
echo ============================================================
echo   Sending now...
echo ============================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo Python not installed. Install from python.org with "Add to PATH" checked.
    pause
    exit /b 1
)

REM Ensure sendgrid library is installed quietly
python -m pip install sendgrid --quiet --upgrade 2>nul

python send_rfi_emails.py

echo.
echo ============================================================
echo   DONE. Check your inbox at amit@superstarscontracting.com
echo   (gmail / outlook / wherever that account points to).
echo.
echo   If you don't see them in 60 seconds, also check Spam.
echo ============================================================
echo.
pause
