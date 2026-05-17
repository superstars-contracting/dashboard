@echo off
title Superstars - Generate CoF PDF

cd /d "%~dp0"

echo ============================================================
echo   GENERATING CoF PDF AT EXACT ID-1 SIZE (85.6 x 53.98 mm)
echo ============================================================
echo.

REM Try common Chrome install locations
set CHROME=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
)
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
    set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
)
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" (
    set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
)

if not defined CHROME (
    echo [!] Chrome not found in standard locations.
    echo.
    echo FALLBACK: open cof_card_print.html in your browser, then:
    echo   - Press Ctrl+P
    echo   - Destination: Save as PDF
    echo   - Margins: None
    echo   - Background graphics: ON
    echo   - Save
    echo.
    pause
    exit /b 1
)

echo [+] Found Chrome: %CHROME%
echo [+] Generating PDF...
echo.

REM Unique filename so a previously-open PDF doesn't block this run
set "OUTPUT=cof_card_sample_%RANDOM%.pdf"
set "INPUT_URL=file:///%CD:\=/%/cof_card_print.html"

"%CHROME%" --headless --disable-gpu --no-pdf-header-footer ^
    --print-to-pdf="%OUTPUT%" ^
    --print-to-pdf-no-header ^
    "%INPUT_URL%"

if exist "%OUTPUT%" (
    echo.
    echo ============================================================
    echo   SUCCESS! PDF saved to:
    echo     %CD%\%OUTPUT%
    echo.
    echo   Opening it now...
    echo ============================================================
    start "" "%OUTPUT%"
) else (
    echo.
    echo [!] PDF generation failed.
    echo     If the previous PDF is open in a viewer, close it and try again.
    echo     Or use the manual fallback:
    echo       1. Open cof_card_print.html in Chrome
    echo       2. Ctrl+P, Save as PDF, Margins=None, Background graphics=ON
)

echo.
pause
