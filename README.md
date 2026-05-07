# AutoSnap

AutoSnap is an open-source screenshot archiver. It does not replace your system screenshot shortcuts. It watches normal screenshot folders and the clipboard, copies new screenshots into a predictable archive, indexes them in SQLite, and lets you search them later.

This repository currently contains a Windows-first v0 implemented in Python/Tkinter so it can run with a small dependency set before the native Tauri app is built.

## v0 Features

- Watches screenshot folders without changing existing screenshot behavior.
- Polls the clipboard so `Win+Shift+S` screenshots can be archived even when Windows does not save a file.
- Archives images as `YYYY/MM/DD/YYYY-MM-DD_HH-mm-ss_<category>_<hash>.png`.
- Keeps originals by default; AutoSnap copies and indexes instead of stealing files.
- Deduplicates by SHA-256.
- Stores metadata in SQLite and writes sidecar JSON files.
- Provides a local Tkinter UI for timeline browsing and keyword search.
- Optional OpenAI vision annotation via BYOK. If no API key is configured, the app still works as a clean local screenshot archive.

## Windows Quick Start

1. Install Python 3.11+ from <https://www.python.org/downloads/windows/> and tick **Add python.exe to PATH**.
2. Double-click `scripts\windows_install.bat`.
3. Double-click `scripts\windows_run.bat`.
4. Take a screenshot with `Win+Shift+S` or `Win+PrtScn`.

Default archive location:

```text
%USERPROFILE%\Documents\AutoSnap
```

Default configuration location:

```text
%APPDATA%\AutoSnap\config.json
```

## Optional AI Annotation

AutoSnap v0 never requires AI. To enable OpenAI annotation:

```powershell
setx OPENAI_API_KEY "sk-..."
setx AUTOSNAP_ENABLE_AI "1"
setx AUTOSNAP_OPENAI_MODEL "gpt-4.1-mini"
```

Restart AutoSnap after setting environment variables. The model name is configurable because model availability changes over time.

## Development

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m autosnap
```

On macOS/Linux, use the equivalent venv activation command and run:

```bash
python -m autosnap
```

Run tests:

```bash
python -m unittest discover -s tests
```

Build a Windows exe:

```bat
scripts\windows_build_exe.bat
```

The exe build uses PyInstaller and is intended as a convenience artifact for v0 testing. The long-term product design still targets a signed native installer.
