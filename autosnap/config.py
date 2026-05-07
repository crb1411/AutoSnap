from __future__ import annotations

import json
import os
import platform
from dataclasses import asdict, dataclass
from pathlib import Path


def _windows_appdata() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming"))


def config_dir() -> Path:
    if platform.system() == "Windows":
        return _windows_appdata() / "AutoSnap"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "autosnap"


def default_archive_dir() -> Path:
    documents = Path.home() / "Documents"
    return documents / "AutoSnap"


def default_watch_dirs() -> list[str]:
    home = Path.home()
    candidates = [
        home / "Pictures" / "Screenshots",
        home / "OneDrive" / "Pictures" / "Screenshots",
        home / "Desktop",
    ]
    if platform.system() == "Darwin":
        candidates = [home / "Desktop", home / "Pictures" / "Screenshots"]
    return [str(path) for path in candidates if path.exists()]


@dataclass
class Settings:
    archive_dir: str
    watch_dirs: list[str]
    enable_clipboard: bool = True
    keep_originals: bool = True
    enable_ai: bool = False
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1-mini"
    poll_interval_sec: float = 1.5
    process_existing_on_start: bool = False
    language: str = "zh_CN"
    minimize_to_tray_on_close: bool = True
    start_in_tray: bool = False
    start_watching_on_launch: bool = False

    @classmethod
    def defaults(cls) -> "Settings":
        enable_ai = os.environ.get("AUTOSNAP_ENABLE_AI", "").lower() in {"1", "true", "yes"}
        return cls(
            archive_dir=str(default_archive_dir()),
            watch_dirs=default_watch_dirs(),
            enable_ai=enable_ai,
            openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
            openai_model=os.environ.get("AUTOSNAP_OPENAI_MODEL", "gpt-4.1-mini"),
        )


class SettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (config_dir() / "config.json")

    def load(self) -> Settings:
        defaults = Settings.defaults()
        if not self.path.exists():
            self.save(defaults)
            return defaults

        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return defaults

        merged = asdict(defaults)
        merged.update({k: v for k, v in raw.items() if k in merged})
        return Settings(**merged)

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(asdict(settings), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
