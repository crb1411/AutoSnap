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
del /q AutoSnap.spec 2>nul
del /q AutoSnap-Setup.spec 2>nul

echo Building app payload (onedir)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onedir --name AutoSnap --icon assets\autosnap.ico autosnap_launcher.py
if errorlevel 1 exit /b 1
if not exist "dist\AutoSnap\AutoSnap.exe" (
  echo ERROR: dist\AutoSnap\AutoSnap.exe was not produced.
  exit /b 1
)

mkdir installer-dist
echo Building bootstrap installer (onefile)...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --onefile --distpath installer-dist --workpath build\installer --name AutoSnap-Setup --icon assets\autosnap.ico --add-data "dist\AutoSnap;payload\AutoSnap" installer\bootstrap.py
if errorlevel 1 exit /b 1

if not exist "installer-dist\AutoSnap-Setup.exe" (
  echo ERROR: installer-dist\AutoSnap-Setup.exe missing after build.
  echo Listing installer-dist:
  dir installer-dist /s
  exit /b 1
)

echo.
echo Installer built: installer-dist\AutoSnap-Setup.exe
dir installer-dist\AutoSnap-Setup.exe
