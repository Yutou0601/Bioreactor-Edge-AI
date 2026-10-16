@echo off
cd /d "%~dp0"

REM ============================================================
REM  One-click launcher for the bioreactor monitoring system.
REM
REM  NOTE: keep this file ASCII-only. cmd.exe reads .bat files with the
REM  system ANSI codepage, so UTF-8 Chinese here becomes garbage commands
REM  and the launcher fails in a confusing way.
REM
REM  ROLE SINCE ARCHITECTURE B (2026-10-15): STANDALONE FALLBACK ONLY.
REM  Normally the backend, database and web page run on the Jetson Orin NX,
REM  and this PC only runs the vendor logger plus monitor_uploader
REM  (see docs/system/ deployment guide for architecture B, sections 6 and 9).
REM  Run this file only when the Jetson is down: it starts the whole
REM  system on this one machine as a single process:
REM
REM      uvicorn main:app --port 8000   (listens on 127.0.0.1 only)
REM          /api/*  backend
REM          /       frontend dist/ (served by StaticFiles)
REM
REM  Do NOT put this file in the Startup folder under architecture B:
REM  it would run a second backend next to the Jetson's.
REM  No SSH, no npm at runtime, no MQTT broker required.
REM  The old start_all.bat / sync_jetson.bat are obsolete.
REM ============================================================

set PANEL=launcher.pyw

if exist "edge_backend\venv\Scripts\pythonw.exe" (
    start "" "edge_backend\venv\Scripts\pythonw.exe" "%PANEL%"
    exit /b 0
)

where pythonw >nul 2>&1
if not errorlevel 1 (
    start "" pythonw "%PANEL%"
    exit /b 0
)

where python >nul 2>&1
if not errorlevel 1 (
    echo [INFO] pythonw not found; using python instead.
    echo        An extra console window will stay open - this is normal.
    python "%PANEL%"
    exit /b 0
)

echo.
echo [ERROR] No Python interpreter found.
echo         Install Python, or make sure edge_backend\venv exists.
echo.
pause
exit /b 1
