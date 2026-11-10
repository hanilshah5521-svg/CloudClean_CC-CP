@echo off
REM CloudClean on one address, without Docker: builds the web app once, then
REM runs the API (which also serves the web app) and the background worker.
REM Open it at http://localhost:8000, or publish it with a free HTTPS tunnel
REM (DEPLOY.md, option A). Set PUBLIC_URL in .env to that https address.
REM Close the two CloudClean windows to stop.
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"

call "%ROOT%\scripts\start-windows.bat" --setup-only
if errorlevel 1 exit /b 1

echo === Building the web app ===
pushd frontend
REM A production build calls the API on its own address (no VITE_API_URL needed).
call npm run build
if errorlevel 1 (
  popd
  echo Building the web app failed - see above.
  pause
  exit /b 1
)
popd

echo === Starting CloudClean ===
start "CloudClean (production)" /d "%ROOT%\backend" cmd /k "set STATIC_DIR=%ROOT%\frontend\dist&& venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --proxy-headers --forwarded-allow-ips=*"
start "CloudClean worker" /d "%ROOT%\backend" cmd /k venv\Scripts\python -m app.worker
timeout /t 6 /nobreak >nul
start "" http://localhost:8000
echo.
echo CloudClean is running at http://localhost:8000
echo Publish it with:  tailscale funnel 8000   (see DEPLOY.md)
pause
exit /b 0
