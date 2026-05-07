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

echo Building bootstrap installer...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --windowed --onefile --name AutoSnap-Setup --icon assets\autosnap.ico --add-data "dist\AutoSnap;payload\AutoSnap" installer\bootstrap.py
if errorlevel 1 exit /b 1

mkdir installer-dist 2>nul
copy /y dist\AutoSnap-Setup.exe installer-dist\AutoSnap-Setup.exe
if errorlevel 1 exit /b 1

echo.
echo Installer built: installer-dist\AutoSnap-Setup.exe
