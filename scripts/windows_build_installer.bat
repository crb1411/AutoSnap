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

where makensis >nul 2>nul
if errorlevel 1 (
  echo NSIS makensis is not installed or not on PATH.
  echo Download it from https://nsis.sourceforge.io/Download, then rerun this script.
  exit /b 1
)

pushd installer
makensis AutoSnap.nsi
set INSTALLER_EXIT=%ERRORLEVEL%
popd
if not "%INSTALLER_EXIT%"=="0" exit /b %INSTALLER_EXIT%

echo.
echo Installer built: installer-dist\AutoSnap-Setup.exe
