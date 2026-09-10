@echo off
REM ===================================================================
REM  RELEASE  --  run this on the DEVELOPMENT laptop
REM
REM  Builds the frontend, runs the full system test, commits the built
REM  dist/ and tags the release, then pushes to GitHub.
REM
REM  The monitoring PC updates by running update.bat, which does a
REM  git pull.  That is why dist/ MUST be committed here: the field
REM  machine has no node/npm, so an unbuilt frontend means a 404.
REM
REM  Nothing is pushed if the system test fails.  That gate is the
REM  point of this script -- a broken release on the field machine is
REM  much more expensive than a failed build here.
REM
REM  ASCII only: cmd.exe reads .bat with the system ANSI codepage.
REM ===================================================================
setlocal
cd /d "%~dp0"

if "%~1"=="" (
  echo.
  echo   Usage:  release.bat ^<version^>
  echo   Example: release.bat v1.3.0
  echo.
  echo   Recent tags:
  git tag --sort=-creatordate 2>nul | head -5
  exit /b 1
)
set VERSION=%~1

echo.
echo === 1/5  Checking the working tree =================================
git diff --quiet
if errorlevel 1 (
  echo   [!] You have uncommitted changes.  Commit them first --
  echo       a release must correspond to a commit you can go back to.
  git status --short
  exit /b 1
)
echo   clean

echo.
echo === 2/5  Building the frontend ====================================
pushd web_frontend
call npm run build
if errorlevel 1 ( echo   [!] Build failed. & popd & exit /b 1 )
popd
echo   built

echo.
echo === 3/5  System test =============================================
pushd edge_backend
if exist venv\Scripts\python.exe (
  venv\Scripts\python.exe system_test.py
) else (
  python system_test.py
)
if errorlevel 1 ( echo   [!] System test FAILED -- not releasing. & popd & exit /b 1 )
popd

echo.
echo === 4/5  Committing the build ====================================
git add web_frontend/dist
git diff --cached --quiet
if errorlevel 1 (
  git commit -m "build: frontend for %VERSION%"
) else (
  echo   dist/ unchanged, nothing to commit
)

echo.
echo === 5/5  Tagging and pushing =====================================
git tag -a %VERSION% -m "release %VERSION%"
if errorlevel 1 ( echo   [!] Tag %VERSION% already exists. & exit /b 1 )
git push origin HEAD
if errorlevel 1 ( echo   [!] Push failed. & exit /b 1 )
git push origin %VERSION%
if errorlevel 1 ( echo   [!] Tag push failed. & exit /b 1 )

echo.
echo   Released %VERSION%.
echo   On the monitoring PC, run:  update.bat
echo.
endlocal
