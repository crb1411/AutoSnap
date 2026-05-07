from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Optional

try:
    import pystray
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    pystray = None  # type: ignore
    Image = None  # type: ignore


class TrayController:
    """Wraps pystray so the rest of the app stays import-safe even when
    pystray cannot load (headless CI, broken tray on some Linux WMs)."""

    def __init__(
        self,
        icon_path: Path,
        on_show: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_quit: Callable[[], None],
        labels: dict[str, str],
    ) -> None:
        self.icon_path = icon_path
        self.on_show = on_show
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_quit = on_quit
        self.labels = labels
        self._icon: Optional["pystray.Icon"] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def available(self) -> bool:
        return pystray is not None and Image is not None

    def start(self) -> None:
        if not self.available or self._icon is not None:
            return
        try:
            image = Image.open(self.icon_path)
        except Exception:
            return
        menu = pystray.Menu(
            pystray.MenuItem(self.labels["show"], lambda _icon, _item: self.on_show(), default=True),
            pystray.MenuItem(self.labels["start"], lambda _icon, _item: self.on_start()),
            pystray.MenuItem(self.labels["stop"], lambda _icon, _item: self.on_stop()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(self.labels["quit"], lambda _icon, _item: self._quit()),
        )
        self._icon = pystray.Icon("AutoSnap", image, self.labels["tooltip_idle"], menu)
        self._thread = threading.Thread(target=self._icon.run, daemon=True)
        self._thread.start()

    def update_tooltip(self, watching: bool) -> None:
        if self._icon is None:
            return
        try:
            self._icon.title = self.labels["tooltip_watching" if watching else "tooltip_idle"]
        except Exception:
            pass

    def stop(self) -> None:
        if self._icon is None:
            return
        try:
            self._icon.stop()
        except Exception:
            pass
        self._icon = None
        self._thread = None

    def _quit(self) -> None:
        self.on_quit()
        self.stop()
