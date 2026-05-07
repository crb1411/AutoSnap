@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  call "%~dp0windows_install.bat"
)

".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 exit /b 1

".venv\Scripts\python.exe" scripts\create_icon.py
if errorlevel 1 exit /b 1

rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
rmdir /s /q installer-dist 2>nul

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed --onedir --name AutoSnap --icon assets\autosnap.ico autosnap_launcher.py
if errorlevel 1 exit /b 1

where iscc >nul 2>nul
if errorlevel 1 (
  echo Inno Setup compiler is not installed or not on PATH.
  echo Download it from https://jrsoftware.org/isdl.php, then rerun this script.
  exit /b 1
)

iscc installer\AutoSnap.iss
if errorlevel 1 exit /b 1

echo.
echo Installer built: installer-dist\AutoSnap-Setup.exe
