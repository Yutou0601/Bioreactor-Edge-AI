@echo off
REM ===================================================================
REM  MONITOR UPLOADER SETUP  --  run on the MONITORING PC (architecture B)
REM
REM  What this machine does after setup:
REM     vendor logger (COM4) -> CSV files -> monitor_uploader -> USB -> Jetson
REM  Backend, database and web page all run on the Jetson.  This PC only
REM  reads the CSV files and sends new lines.  Open the page in a browser:
REM     http://192.168.55.1:8000
REM
REM  It NEVER opens a COM port, opens NO inbound port on this PC, needs no
REM  administrator rights, and does not touch the vendor logger.
REM  Undo:  deploy\monitor_uploader_remove.bat
REM
REM  Usage (normal user):   deploy\monitor_uploader_setup.bat
REM  First run asks for the CSV folder and the ingest token.  The token is
REM  REACTOR_INGEST_TOKEN from the Jetson's .env; it is never in git --
REM  bring it on paper or a USB stick.
REM
REM  Steps: python -> settings -> USB link -> one upload -> reconcile
REM         -> autostart at logon -> desktop shortcut
REM  Stops at the first failure.  Autostart is only installed after the
REM  test upload succeeded.
REM
REM  Autostart is a shortcut in the user's Startup folder, NOT a scheduled
REM  task: an at-logon task needs administrator rights on most machines.
REM
REM  ASCII only: cmd.exe reads .bat with the system ANSI codepage.
REM ===================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0.."
set "ROOT=%CD%"
set "EB=%ROOT%\edge_backend"
set "ENVF=%EB%\.env"
set "LOGF=%EB%\uploader.log"
REM  REACTOR_JETSON_IP overrides the USB address (for testing over Tailscale)
set "JETSON=192.168.55.1"
if defined REACTOR_JETSON_IP set "JETSON=%REACTOR_JETSON_IP%"
REM  Ask Windows for the real folders: with OneDrive, %USERPROFILE%\Desktop
REM  may not exist at all.
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Startup')"`) do set "STARTUP=%%d"
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESK=%%d"
if not defined STARTUP set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
if not defined DESK set "DESK=%USERPROFILE%\Desktop"
set "LNK=%STARTUP%\Bioreactor uploader.lnk"

echo.
echo ============================================================
echo   Bioreactor -- monitoring PC uploader setup (architecture B)
echo ============================================================

REM ---- 1  Python (stdlib only; any 3.8+ works) -----------------------
set "PY="
if exist "%EB%\venv\Scripts\python.exe" set "PY=%EB%\venv\Scripts\python.exe"
if not defined PY (
  REM  skip the Microsoft Store stub (it opens the Store and hangs)
  for /f "delims=" %%i in ('where python 2^>nul ^| find /v /i "WindowsApps"') do (
    if not defined PY set "PY=%%i"
  )
)
if not defined PY (
  echo   [!] Python not found ^(or only the Microsoft Store stub^).
  echo       Install Python 3.8+ from python.org, tick "Add to PATH",
  echo       then run this again.
  goto :fail
)
"!PY!" -c "import sys; assert sys.version_info >= (3, 8)" >nul 2>&1
if errorlevel 1 ( echo   [!] Python too old or broken: !PY! & goto :fail )
for %%d in ("!PY!") do set "PYW=%%~dpdpythonw.exe"
if not exist "!PYW!" set "PYW=!PY!"
echo   [1/7] python   !PY!

REM ---- 2  settings (.env) --------------------------------------------
REM  An existing .env (from the old all-in-one install) is kept; only the
REM  keys this uploader needs are added when missing.
if not exist "%ENVF%" (
  echo # created by monitor_uploader_setup.bat %DATE% %TIME%> "%ENVF%"
)
call :ensure REACTOR_DATA_DIR "CSV folder written by the vendor logger"
if errorlevel 1 goto :fail
call :ensure REACTOR_INGEST_TOKEN "Ingest token (same as on the Jetson)"
if errorlevel 1 goto :fail
call :ensure_default REACTOR_UPLOAD_URL http://%JETSON%:8000
call :ensure_default REACTOR_STATION BTP-1
set "DATADIR="
for /f "usebackq tokens=1* delims==" %%a in (`findstr /b "REACTOR_DATA_DIR=" "%ENVF%"`) do set "DATADIR=%%b"
set "DATADIR=!DATADIR:"=!"
if not exist "!DATADIR!\" (
  echo   [!] CSV folder does not exist: !DATADIR!
  echo       Fix REACTOR_DATA_DIR in %ENVF% and run this again.
  goto :fail
)
set NCSV=0
for %%f in ("!DATADIR!\BTP_Sensor_log-*.csv") do set /a NCSV+=1
if !NCSV! EQU 0 (
  echo   [!] No BTP_Sensor_log-*.csv in !DATADIR!
  echo       Is this really the folder the vendor logger writes to?
  goto :fail
)
echo   [2/7] settings %ENVF%
echo         !NCSV! CSV files in !DATADIR!

REM ---- 3  USB link to the Jetson --------------------------------------
ping -n 2 -w 1500 %JETSON% >nul
if errorlevel 1 (
  echo   [!] Cannot reach the Jetson at %JETSON%.
  echo       Check: USB-C cable in the Jetson's device-mode port, Jetson
  echo       powered on ^(allow 2 minutes after power-on^), and a new
  echo       network adapter visible in ncpa.cpl.  Then run this again.
  goto :fail
)
echo   [3/7] USB link %JETSON% reachable

REM ---- 4  one upload ---------------------------------------------------
echo   [4/7] test upload ^(first run sends the whole folder; may take minutes^)
"!PY!" "%EB%\monitor_uploader.py" --once --log "%LOGF%"
if errorlevel 1 (
  echo   [!] Upload failed -- see above and %LOGF%
  echo       HTTP 401: token differs from the Jetson's .env
  echo       HTTP 403 REACTOR_ALLOW_NETS: request did not come over USB
  goto :fail
)

REM ---- 5  reconcile ----------------------------------------------------
echo   [5/7] reconcile: lines on this PC vs rows on the Jetson
"!PY!" "%EB%\monitor_uploader.py" --check
if errorlevel 1 (
  echo   [*] Some days differ.  Usually only TODAY ^(still being written^)
  echo       or files with header lines.  Not fatal -- review the list above.
)

REM ---- 6  autostart at logon (Startup folder; no admin needed) --------
if exist "%LNK%" del "%LNK%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\deploy\make_shortcut.ps1" ^
  -Lnk "%LNK%" -Target "!PYW!" -Script "%EB%\monitor_uploader.py" -WorkDir "%EB%" >nul 2>&1
if not exist "%LNK%" (
  echo   [!] Could not create the Startup shortcut.  Creating a .cmd instead.
  set "LNK=%STARTUP%\Bioreactor uploader.cmd"
  > "!LNK!" echo @start "" "!PYW!" "%EB%\monitor_uploader.py"
)
REM  start it now (a second copy exits by itself: single-instance lock)
start "" "!PYW!" "%EB%\monitor_uploader.py"
echo   [6/7] autostart at logon: !LNK!
echo         uploader started in the background ^(log: %LOGF%^)

set "URLF=%DESK%\Bioreactor monitor.url"
> "%URLF%" (
  echo [InternetShortcut]
  echo URL=http://%JETSON%:8000/
)
echo   [7/7] desktop shortcut  %URLF%

echo.
echo ============================================================
echo   Done.  Open http://%JETSON%:8000  ^(desktop shortcut^)
echo   Uploader log:  %LOGF%
echo   Undo:          deploy\monitor_uploader_remove.bat
echo ============================================================
echo.
pause
exit /b 0

:fail
echo.
echo   Setup stopped.  Autostart was NOT installed.
echo.
pause
exit /b 1

REM ---- helpers ---------------------------------------------------------
:ensure
REM  %1 key, %2 prompt.  Ask only when the key is missing or empty.
findstr /b /r /c:"%~1=." "%ENVF%" >nul 2>&1
if not errorlevel 1 exit /b 0
set "VAL="
set /p "VAL=  %~2: "
if not defined VAL (
  echo   [!] %~1 is required.
  exit /b 1
)
REM  leading blank line: the old .env may not end with a newline
>> "%ENVF%" (
  echo.
  echo %~1=!VAL!
)
exit /b 0

:ensure_default
findstr /b /r /c:"%~1=." "%ENVF%" >nul 2>&1
if not errorlevel 1 exit /b 0
>> "%ENVF%" (
  echo.
  echo %~1=%~2
)
exit /b 0
