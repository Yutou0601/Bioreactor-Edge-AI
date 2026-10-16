@echo off
REM ===================================================================
REM  MONITOR UPLOADER REMOVE  --  undo monitor_uploader_setup.bat
REM
REM  Stops the running uploader, removes the Startup entry and the desktop
REM  shortcut.  KEEPS edge_backend\.env, .uploader_state.json and the log:
REM  re-running setup then continues where it stopped instead of
REM  re-sending everything.  CSV files and the vendor logger are untouched.
REM
REM  ASCII only: cmd.exe reads .bat with the system ANSI codepage.
REM ===================================================================
setlocal
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Startup')"`) do set "STARTUP=%%d"
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESK=%%d"

echo.
echo   Stopping the uploader...
powershell -NoProfile -Command ^
  "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*monitor_uploader.py*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; 'stopped pid ' + $_.ProcessId }"

for %%f in ("%STARTUP%\Bioreactor uploader.lnk" "%STARTUP%\Bioreactor uploader.cmd" "%DESK%\Bioreactor monitor.url") do (
  if exist %%f ( del %%f & echo   removed %%~f )
)
echo.
echo   Done.  Settings and upload progress were kept in edge_backend\.
echo.
pause
endlocal
