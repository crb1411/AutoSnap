@echo off
setlocal
cd /d "%~dp0\.."

where python >nul 2>nul
if errorlevel 1 (
  echo Python 3.11+ was not found on PATH.
  echo Install it from https://www.python.org/downloads/windows/ and tick "Add python.exe to PATH".
  pause
  exit /b 1
)

python -m venv .venv
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

echo.
echo AutoSnap dependencies installed.
echo Run scripts\windows_run.bat to start the app.
pause
