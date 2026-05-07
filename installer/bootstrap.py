from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tkinter as tk
import winreg
from pathlib import Path
from tkinter import messagebox


APP_NAME = "AutoSnap"
PUBLISHER = "AutoSnap contributors"


def main() -> None:
    root = tk.Tk()
    root.withdraw()

    source = _payload_dir()
    if not source.exists():
        messagebox.showerror(APP_NAME, f"Installer payload was not found:\n{source}")
        return

    install_dir = Path(os.environ["LOCALAPPDATA"]) / "Programs" / APP_NAME
    ok = messagebox.askyesno(
        APP_NAME,
        f"Install {APP_NAME} to:\n\n{install_dir}\n\nThis does not require administrator permission.",
    )
    if not ok:
        return

    try:
        _install(source, install_dir)
    except Exception as exc:
        messagebox.showerror(APP_NAME, f"Install failed:\n{exc}")
        return

    launch = messagebox.askyesno(APP_NAME, f"{APP_NAME} was installed successfully.\n\nLaunch it now?")
    if launch:
        subprocess.Popen([str(install_dir / "AutoSnap.exe")], cwd=str(install_dir))


def _payload_dir() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "payload" / "AutoSnap"


def _install(source: Path, install_dir: Path) -> None:
    if install_dir.exists():
        shutil.rmtree(install_dir)
    install_dir.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, install_dir)
    _write_uninstaller(install_dir)
    _create_shortcuts(install_dir)
    _write_uninstall_registry(install_dir)


def _write_uninstaller(install_dir: Path) -> None:
    uninstall = install_dir / "Uninstall AutoSnap.bat"
    uninstall.write_text(
        "\n".join(
            [
                "@echo off",
                "setlocal",
                f'rmdir /s /q "%APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\{APP_NAME}" 2>nul',
                f'reg delete "HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\{APP_NAME}" /f >nul 2>nul',
                'cd /d "%LOCALAPPDATA%\\Programs"',
                f'rmdir /s /q "{APP_NAME}"',
            ]
        ),
        encoding="utf-8",
    )


def _create_shortcuts(install_dir: Path) -> None:
    start_dir = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / APP_NAME
    start_dir.mkdir(parents=True, exist_ok=True)
    _shortcut(start_dir / f"{APP_NAME}.lnk", install_dir / "AutoSnap.exe", install_dir)
    _shortcut(start_dir / f"Uninstall {APP_NAME}.lnk", install_dir / "Uninstall AutoSnap.bat", install_dir)


def _shortcut(link: Path, target: Path, workdir: Path) -> None:
    ps = f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut('{str(link)}')
$shortcut.TargetPath = '{str(target)}'
$shortcut.WorkingDirectory = '{str(workdir)}'
$shortcut.Save()
"""
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], check=True)


def _write_uninstall_registry(install_dir: Path) -> None:
    key_path = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_NAME}"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, PUBLISHER)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, "0.1.0")
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(install_dir / "AutoSnap.exe"))
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, str(install_dir / "Uninstall AutoSnap.bat"))


if __name__ == "__main__":
    main()
