from __future__ import annotations

import json
import os
import platform
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .annotator import AnnotationService
from .archiver import Archiver
from .config import SettingsStore
from .db import AutoSnapDB
from .models import ArchiveResult
from .watcher import AutoSnapWatcher


class AutoSnapApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AutoSnap")
        self.geometry("1060x720")
        self.minsize(860, 560)

        self.store = SettingsStore()
        self.settings = self.store.load()
        self.archive_root = Path(self.settings.archive_dir).expanduser()
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.db = AutoSnapDB(self.archive_root / "_index" / "autosnap.db")
        self.archiver = Archiver(self.archive_root, self.db)
        self.annotator = AnnotationService(model=self.settings.openai_model)
        self.watcher: AutoSnapWatcher | None = None
        self.events: queue.Queue[str] = queue.Queue()
        self.thumbnail_refs: list[ImageTk.PhotoImage] = []

        self._build_ui()
        self.refresh()
        self.after(500, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=(12, 10))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(3, weight=1)

        self.start_btn = ttk.Button(top, text="Start watching", command=self.start_watching)
        self.start_btn.grid(row=0, column=0, padx=(0, 8))
        ttk.Button(top, text="Stop", command=self.stop_watching).grid(row=0, column=1, padx=(0, 8))
        ttk.Button(top, text="Import folder", command=self.import_folder).grid(row=0, column=2, padx=(0, 8))
        ttk.Button(top, text="Open archive", command=lambda: self._open_path(self.archive_root)).grid(row=0, column=4, padx=(8, 0))
        ttk.Button(top, text="AI annotate backlog", command=self.annotate_backlog).grid(row=0, column=5, padx=(8, 0))

        search = ttk.Frame(self, padding=(12, 0, 12, 8))
        search.grid(row=1, column=0, sticky="ew")
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text="Search").grid(row=0, column=0, padx=(0, 8))
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.search_var)
        entry.grid(row=0, column=1, sticky="ew")
        entry.bind("<Return>", lambda _event: self.refresh())
        ttk.Button(search, text="Refresh", command=self.refresh).grid(row=0, column=2, padx=(8, 0))

        body = ttk.Frame(self, padding=(12, 0, 12, 8))
        body.grid(row=2, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(body, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.grid_frame = ttk.Frame(self.canvas)
        self.grid_frame.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", self._resize_canvas_window)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        self.status_var = tk.StringVar()
        self.status_var.set(self._status_text())
        status = ttk.Label(self, textvariable=self.status_var, anchor="w", padding=(12, 4))
        status.grid(row=3, column=0, sticky="ew")

    def start_watching(self) -> None:
        if self.watcher is not None:
            return
        watch_dirs = [Path(item).expanduser() for item in self.settings.watch_dirs]
        if not watch_dirs:
            messagebox.showinfo("AutoSnap", "No watch folders configured. Use Import folder for existing screenshots.")
        self.watcher = AutoSnapWatcher(
            archiver=self.archiver,
            watch_dirs=watch_dirs,
            enable_clipboard=self.settings.enable_clipboard,
            ai_enabled=self.settings.enable_ai and self.annotator.available,
            poll_interval=self.settings.poll_interval_sec,
            on_archive=self._on_archived,
            on_error=self._on_error,
            process_existing_on_start=self.settings.process_existing_on_start,
        )
        self.watcher.start()
        self.status_var.set(self._status_text("watching"))

    def stop_watching(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        self.status_var.set(self._status_text("stopped"))

    def import_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose a screenshot folder to import")
        if not folder:
            return
        threading.Thread(target=self._import_folder_worker, args=(Path(folder),), daemon=True).start()

    def annotate_backlog(self) -> None:
        if not self.annotator.available:
            messagebox.showinfo("AutoSnap", "Set OPENAI_API_KEY and AUTOSNAP_ENABLE_AI=1 to enable annotation.")
            return
        threading.Thread(target=self._annotate_backlog_worker, daemon=True).start()

    def refresh(self) -> None:
        rows = self.db.search(self.search_var.get(), limit=160)
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.thumbnail_refs.clear()

        if not rows:
            ttk.Label(
                self.grid_frame,
                text="No screenshots yet. Start watching, then take a screenshot.",
                padding=24,
            ).grid(row=0, column=0, sticky="w")
            return

        columns = 4
        for idx, row in enumerate(rows):
            card = ttk.Frame(self.grid_frame, padding=8, relief="ridge")
            card.grid(row=idx // columns, column=idx % columns, sticky="nsew", padx=6, pady=6)
            image_path = self.archive_root / row["archived_path"]
            thumb = self._load_thumbnail(image_path)
            if thumb is not None:
                label = ttk.Label(card, image=thumb)
                label.grid(row=0, column=0, sticky="n")
                self.thumbnail_refs.append(thumb)
                label.bind("<Double-Button-1>", lambda _event, p=image_path: self._open_path(p))
            title = row["title"] or Path(row["archived_path"]).name
            meta = f"{row['category']} | {self._format_ms(row['captured_at'])}"
            ttk.Label(card, text=title, width=28, wraplength=220).grid(row=1, column=0, sticky="w", pady=(6, 0))
            ttk.Label(card, text=meta, foreground="#555555").grid(row=2, column=0, sticky="w")

    def _import_folder_worker(self, folder: Path) -> None:
        count = 0
        for path in folder.iterdir():
            if not path.is_file():
                continue
            result = self.archiver.archive_file(path, ai_enabled=self.settings.enable_ai and self.annotator.available)
            if result and not result.is_duplicate:
                count += 1
        self.events.put(f"Imported {count} screenshots from {folder}")

    def _annotate_backlog_worker(self) -> None:
        count = 0
        for row in self.db.pending_ai(limit=50):
            image_path = self.archive_root / row["archived_path"]
            annotation = self.annotator.annotate(image_path)
            if annotation:
                self.db.add_annotation(row["id"], annotation)
                count += 1
            else:
                self.db.mark_ai_failed(row["id"])
        self.events.put(f"AI annotation finished: {count} screenshots annotated")

    def _on_archived(self, result: ArchiveResult) -> None:
        if self.settings.enable_ai and self.annotator.available:
            threading.Thread(target=self._annotate_one, args=(result,), daemon=True).start()
        self.events.put(f"Archived {result.archived_path.name}")

    def _annotate_one(self, result: ArchiveResult) -> None:
        annotation = self.annotator.annotate(result.archived_path)
        if annotation:
            self.db.add_annotation(result.id, annotation)
            self.events.put(f"AI annotated {result.archived_path.name}")
        else:
            self.db.mark_ai_failed(result.id)

    def _on_error(self, message: str) -> None:
        self.events.put(message)

    def _drain_events(self) -> None:
        changed = False
        while True:
            try:
                message = self.events.get_nowait()
            except queue.Empty:
                break
            self.status_var.set(self._status_text(message))
            changed = True
        if changed:
            self.refresh()
        self.after(800, self._drain_events)

    def _load_thumbnail(self, image_path: Path) -> ImageTk.PhotoImage | None:
        thumb_path = self.archiver.ensure_thumbnail(image_path)
        target = thumb_path if thumb_path and thumb_path.exists() else image_path
        try:
            with Image.open(target) as image:
                image.thumbnail((220, 160))
                return ImageTk.PhotoImage(image.copy())
        except Exception:
            return None

    def _resize_canvas_window(self, event) -> None:  # type: ignore[no-untyped-def]
        self.canvas.itemconfigure(self.canvas_window, width=event.width)

    def _status_text(self, extra: str | None = None) -> str:
        ai = "AI on" if self.settings.enable_ai and self.annotator.available else "local only"
        watching = "watching" if self.watcher else "idle"
        dirs = ", ".join(self.settings.watch_dirs) or "no watch folders"
        parts = [watching, ai, f"archive: {self.archive_root}", f"watch: {dirs}"]
        if extra:
            parts.insert(0, extra)
        return "  |  ".join(parts)

    @staticmethod
    def _format_ms(value: int) -> str:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _open_path(path: Path) -> None:
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        elif platform.system() == "Darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def _on_close(self) -> None:
        self.stop_watching()
        self.db.close()
        self.destroy()


def main() -> None:
    app = AutoSnapApp()
    app.mainloop()
