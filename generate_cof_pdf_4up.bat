@echo off
title Superstars - Generate CoF PDF (4-up, 2 pages)

cd /d "%~dp0"

echo ============================================================
echo   CoF PRINT SHEET — 4-UP, 2 PAGES, LETTER
echo   Page 1 = 4 card fronts, Page 2 = 4 card backs
echo   Each card at exact ID-1 size (85.6 x 53.98 mm)
echo ============================================================
echo.

set CHROME=
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if not defined CHROME (
    echo [!] Chrome not found. Manual fallback:
    echo   1. Open cof_card_print_4up.html in Chrome
    echo   2. Ctrl+P, Save as PDF, Margins=None, Background graphics=ON
    pause
    exit /b 1
)

echo [+] Found Chrome: %CHROME%
echo [+] Generating PDF...
echo.

set "OUTPUT=cof_card_4up_%RANDOM%.pdf"
set "INPUT_URL=file:///%CD:\=/%/cof_card_print_4up.html"

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
    echo   2 pages: Page 1 = 4 fronts, Page 2 = 4 backs
    echo   Opening now...
    echo ============================================================
    start "" "%OUTPUT%"
) else (
    echo.
    echo [!] PDF generation failed.
    echo   Close any open cof_card_4up_*.pdf files and try again.
    echo   Or use manual fallback:
    echo     1. Open cof_card_print_4up.html in Chrome
    echo     2. Ctrl+P, Save as PDF, Margins=None, Background graphics=ON
)

echo.
pause
