from __future__ import annotations

import platform
import subprocess
from pathlib import Path


def copy_image_to_clipboard(image_path: Path) -> None:
    """Put the actual image bytes on the system clipboard so it can be
    pasted into editors / chat apps as an image (not a file path).

    Raises NotImplementedError on platforms we have not wired up yet.
    Raises subprocess.CalledProcessError or OSError on other failures.
    """
    system = platform.system()
    if system == "Windows":
        _copy_windows(image_path)
    elif system == "Darwin":
        _copy_macos(image_path)
    elif system == "Linux":
        _copy_linux(image_path)
    else:
        raise NotImplementedError(system)


def _copy_windows(image_path: Path) -> None:
    abs_path = str(image_path.resolve()).replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms; "
        "Add-Type -AssemblyName System.Drawing; "
        f"$img = [System.Drawing.Image]::FromFile('{abs_path}'); "
        "[System.Windows.Forms.Clipboard]::SetImage($img); "
        "$img.Dispose()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-STA", "-Command", script],
        check=True,
        capture_output=True,
    )


def _copy_macos(image_path: Path) -> None:
    abs_path = str(image_path.resolve()).replace('"', '\\"')
    script = f'set the clipboard to (read (POSIX file "{abs_path}") as JPEG picture)'
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True)


def _copy_linux(image_path: Path) -> None:
    mime = "image/png"
    suffix = image_path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        mime = "image/jpeg"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".bmp":
        mime = "image/bmp"
    cmds = [
        ["wl-copy", "--type", mime],
        ["xclip", "-selection", "clipboard", "-t", mime, "-i"],
    ]
    last_err: Exception | None = None
    for cmd in cmds:
        try:
            with image_path.open("rb") as f:
                subprocess.run(cmd, stdin=f, check=True, capture_output=True)
            return
        except FileNotFoundError as err:
            last_err = err
            continue
    raise NotImplementedError(
        "Need wl-copy (Wayland) or xclip (X11) to copy images on Linux"
    ) from last_err
