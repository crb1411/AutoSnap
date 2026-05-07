from __future__ import annotations

import hashlib
import threading
import time
from pathlib import Path
from typing import Callable

from PIL import Image, ImageGrab

from .archiver import Archiver
from .models import ArchiveResult, IMAGE_EXTENSIONS

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer
except Exception:  # pragma: no cover - exercised when watchdog is not installed
    FileSystemEventHandler = object  # type: ignore
    Observer = None  # type: ignore


OnArchive = Callable[[ArchiveResult], None]
OnError = Callable[[str], None]


class AutoSnapWatcher:
    def __init__(
        self,
        archiver: Archiver,
        watch_dirs: list[Path],
        enable_clipboard: bool,
        ai_enabled: bool,
        poll_interval: float,
        on_archive: OnArchive,
        on_error: OnError,
        process_existing_on_start: bool = False,
    ) -> None:
        self.archiver = archiver
        self.watch_dirs = watch_dirs
        self.enable_clipboard = enable_clipboard
        self.ai_enabled = ai_enabled
        self.poll_interval = poll_interval
        self.on_archive = on_archive
        self.on_error = on_error
        self.process_existing_on_start = process_existing_on_start
        self._stop = threading.Event()
        self._observer = None
        self._threads: list[threading.Thread] = []
        self._seen_files: set[Path] = set()
        self._last_clip_hash: str | None = None

    def start(self) -> None:
        self._stop.clear()
        self.watch_dirs = [path for path in self.watch_dirs if path.exists()]
        self._seed_seen_files()
        if Observer is not None:
            self._observer = Observer()
            for directory in self.watch_dirs:
                self._observer.schedule(_ImageEventHandler(self), str(directory), recursive=False)
            self._observer.start()
        else:
            self._start_thread(self._poll_files)
        if self.enable_clipboard:
            self._start_thread(self._poll_clipboard)

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=3)
            self._observer = None
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads.clear()

    def handle_path(self, path: Path) -> None:
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return
        try:
            result = self.archiver.archive_file(path, ai_enabled=self.ai_enabled)
            if result and not result.is_duplicate:
                self.on_archive(result)
        except Exception as exc:
            self.on_error(f"Archive failed for {path}: {exc}")

    def _start_thread(self, target: Callable[[], None]) -> None:
        thread = threading.Thread(target=target, daemon=True)
        thread.start()
        self._threads.append(thread)

    def _seed_seen_files(self) -> None:
        if self.process_existing_on_start:
            return
        for directory in self.watch_dirs:
            for path in directory.iterdir():
                if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS:
                    self._seen_files.add(path.resolve())

    def _poll_files(self) -> None:
        while not self._stop.is_set():
            for directory in self.watch_dirs:
                try:
                    files = list(directory.iterdir())
                except OSError as exc:
                    self.on_error(f"Cannot scan {directory}: {exc}")
                    continue
                for path in files:
                    if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                        continue
                    resolved = path.resolve()
                    if resolved in self._seen_files:
                        continue
                    self._seen_files.add(resolved)
                    self.handle_path(resolved)
            time.sleep(self.poll_interval)

    def _poll_clipboard(self) -> None:
        while not self._stop.is_set():
            try:
                clip = ImageGrab.grabclipboard()
                if isinstance(clip, Image.Image):
                    digest = self._image_digest(clip)
                    if digest != self._last_clip_hash:
                        self._last_clip_hash = digest
                        result = self.archiver.archive_clipboard_image(clip, ai_enabled=self.ai_enabled)
                        if result and not result.is_duplicate:
                            self.on_archive(result)
                elif isinstance(clip, list):
                    for item in clip:
                        path = Path(item)
                        if path.exists():
                            self.handle_path(path)
            except Exception as exc:
                self.on_error(f"Clipboard capture failed: {exc}")
            time.sleep(self.poll_interval)

    @staticmethod
    def _image_digest(image: Image.Image) -> str:
        h = hashlib.sha256()
        h.update(image.mode.encode("utf-8"))
        h.update(str(image.size).encode("utf-8"))
        h.update(image.tobytes())
        return h.hexdigest()


class _ImageEventHandler(FileSystemEventHandler):  # type: ignore[misc]
    def __init__(self, watcher: AutoSnapWatcher) -> None:
        self.watcher = watcher

    def on_created(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.is_directory:
            self.watcher.handle_path(Path(event.src_path))

    def on_moved(self, event) -> None:  # type: ignore[no-untyped-def]
        if not event.is_directory:
            self.watcher.handle_path(Path(event.dest_path))
