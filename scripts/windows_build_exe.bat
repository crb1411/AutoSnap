@echo off
setlocal
cd /d "%~dp0\.."

if not exist ".venv\Scripts\python.exe" (
  call "%~dp0windows_install.bat"
)

".venv\Scripts\python.exe" -m pip install pyinstaller
if errorlevel 1 exit /b 1

".venv\Scripts\pyinstaller.exe" --noconfirm --windowed --name AutoSnap --add-data "README.md;." autosnap\__main__.py
echo.
echo Build complete. See dist\AutoSnap\AutoSnap.exe
pause
