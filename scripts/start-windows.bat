@echo off
REM CloudClean - one-click setup and start for Windows.
REM First run: creates backend\venv and installs packages (a few minutes).
REM Opens three windows (backend, worker, frontend) and the browser.
REM Close those three windows to stop. Pass --setup-only to install without starting.
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"

echo === CloudClean setup ===

REM Find a supported Python: the "py" launcher first, then "python".
set "PY="
for %%v in (3.12 3.13 3.11 3.10) do (
  if not defined PY (
    py -%%v -c "import venv" >nul 2>nul && set "PY=py -%%v"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(not ((3, 10) <= sys.version_info[:2] <= (3, 13)))" >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo Python 3.10 to 3.13 is required ^(3.12 recommended^): https://www.python.org/downloads/
  goto :fail
)
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js 18 or newer is required: https://nodejs.org/
  goto :fail
)
echo Using Python: %PY%

REM Some installed packages sit ~130 characters deep. Unless Windows long
REM paths are enabled, a folder path over ~110 characters breaks the install.
%PY% -c "import sys, winreg; k = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SYSTEM\CurrentControlSet\Control\FileSystem'); sys.exit(winreg.QueryValueEx(k, 'LongPathsEnabled')[0] != 1)" >nul 2>nul
if errorlevel 1 (
  %PY% -c "import os, sys; sys.exit(len(os.getcwd()) > 110)"
  if errorlevel 1 (
    echo This folder's path is too long for Windows:
    echo   %ROOT%
    echo Move the CloudClean folder somewhere short, e.g. C:\CloudClean, and run this again.
    goto :fail
  )
)

if not exist "backend\venv\Scripts\python.exe" (
  echo Creating backend\venv ...
  %PY% -m venv backend\venv
  if errorlevel 1 goto :fail
)
echo Installing backend packages ...
backend\venv\Scripts\python -m pip install --quiet --disable-pip-version-check --upgrade pip
backend\venv\Scripts\python -m pip install --quiet --disable-pip-version-check -r backend\requirements.txt
if errorlevel 1 goto :fail

if not exist "frontend\node_modules" (
  echo Installing frontend packages ...
  pushd frontend
  call npm ci --no-audit --no-fund
  if errorlevel 1 (
    popd
    goto :fail
  )
  popd
)

if /i "%~1"=="--setup-only" (
  echo Setup complete.
  exit /b 0
)

echo === Starting CloudClean ===
start "CloudClean backend" /d "%ROOT%\backend" cmd /k venv\Scripts\python -m uvicorn app.main:app --port 8000
start "CloudClean worker" /d "%ROOT%\backend" cmd /k venv\Scripts\python -m app.worker
start "CloudClean frontend" /d "%ROOT%\frontend" cmd /k npm run dev
timeout /t 8 /nobreak >nul
start "" http://localhost:5173
echo.
echo CloudClean is running at http://localhost:5173 - click "Try Demo Mode".
echo To stop it, close the three CloudClean windows.
pause
exit /b 0

:fail
echo.
echo Setup failed - see the messages above, and TESTING.md ^> Troubleshooting.
pause
exit /b 1
