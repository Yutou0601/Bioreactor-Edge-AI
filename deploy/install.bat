@echo off
REM ===================================================================
REM  INSTALL  --  run this on the MONITORING PC, from the unzipped pack
REM
REM  Works with NO network: the pack ships the Python wheels, so pip
REM  installs from the bundled folder instead of reaching PyPI.
REM
REM  Order matters:
REM    venv -> dependencies -> settings -> SELF CHECK -> start
REM
REM  It does NOT start the service if the self check fails.  Starting a
REM  misconfigured service is worse than not starting: the web page
REM  comes up, everything looks fine, and no data ever arrives.  That
REM  is how the 2026-07-22 silent 17.5 hour gap went unnoticed.
REM
REM  Your own settings and data are never touched:
REM    .env, reactor.db, experiment_runs.json are not in the pack.
REM
REM  ASCII only: cmd.exe reads .bat with the system ANSI codepage.
REM ===================================================================
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   Bioreactor -- install / update from pack
echo ============================================================
if exist VERSION.txt type VERSION.txt
echo.

REM ---- 1  Python ----------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
  echo   [!] Python is not on PATH.
  echo       Install Python 3.9+ and tick "Add python.exe to PATH".
  pause & exit /b 1
)

REM ---- 2  venv -------------------------------------------------------
if not exist edge_backend\venv\Scripts\python.exe (
  echo   Creating virtual environment...
  python -m venv edge_backend\venv
  if errorlevel 1 ( echo   [!] venv creation failed. & pause & exit /b 1 )
) else (
  echo   venv already present.
)
set PY=edge_backend\venv\Scripts\python.exe

REM ---- 3  dependencies (offline first, network only as fallback) -----
echo.
echo   Installing dependencies...
if exist wheels (
  %PY% -m pip install -q --no-index --find-links wheels -r edge_backend\requirements.txt
  if errorlevel 1 (
    echo   [!] Offline install failed.  Trying PyPI in case this machine
    echo       has network right now...
    %PY% -m pip install -q -r edge_backend\requirements.txt
    if errorlevel 1 ( echo   [!] Dependency install FAILED. & pause & exit /b 1 )
  )
) else (
  echo   No bundled wheels -- using PyPI ^(needs network^).
  %PY% -m pip install -q -r edge_backend\requirements.txt
  if errorlevel 1 ( echo   [!] Dependency install FAILED. & pause & exit /b 1 )
)
echo   dependencies OK

REM ---- 4  site settings ----------------------------------------------
echo.
if exist edge_backend\.env (
  echo   edge_backend\.env already present -- your settings are kept.
) else (
  copy /y edge_backend\.env.example edge_backend\.env >nul
  echo   Created edge_backend\.env from the template.
  echo   *** OPEN IT AND SET REACTOR_DATA_DIR TO THIS MACHINE'S CSV FOLDER ***
)

REM ---- 5  self check --------------------------------------------------
echo.
echo ------------------------------------------------------------
%PY% edge_backend\selfcheck.py
if errorlevel 1 (
  echo ------------------------------------------------------------
  echo.
  echo   [!] Self check FAILED.  The service was NOT started.
  echo.
  echo       Fix what is marked above -- usually the data folder path
  echo       in edge_backend\.env -- then run install.bat again.
  echo.
  pause & exit /b 1
)
echo ------------------------------------------------------------

REM ---- 6  start --------------------------------------------------------
echo.
echo   Self check passed.  Starting...
echo.
if exist START.bat (
  start "" START.bat
  echo   Started.  The control panel window should appear.
) else (
  echo   [!] START.bat not found in this folder; start it manually.
)
echo.
pause
endlocal
