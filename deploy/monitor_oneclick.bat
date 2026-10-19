@echo off
REM ===================================================================
REM  ONE-CLICK INSTALL (monitoring PC, architecture B) -- double-click me.
REM  All the logic is in monitor_oneclick.ps1 next to this file.
REM  Preview without changing anything:  monitor_oneclick.bat -DryRun
REM  Normal user, NOT administrator.  ASCII only (cmd reads ANSI).
REM ===================================================================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0monitor_oneclick.ps1" %*
if errorlevel 1 (
  echo.
  echo   One-click install stopped. Read the message above.
  echo.
  pause
  exit /b 1
)
exit /b 0
