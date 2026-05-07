from __future__ import annotations

import os
import platform
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .annotator import AnnotationService
from .archiver import Archiver
from .clipboard import copy_image_to_clipboard
from .config import Settings, SettingsStore
from .db import AutoSnapDB
from .i18n import SUPPORTED_LANGUAGES, Translator
from .models import ArchiveResult
from .tray import TrayController
from .watcher import AutoSnapWatcher


def _bundle_root() -> Path:
    """Return the directory that contains app assets, both in dev and inside
    a PyInstaller --onedir/--onefile bundle."""
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def _icon_path() -> Path | None:
    candidates = [
        _bundle_root() / "assets" / "autosnap.ico",
        Path(__file__).resolve().parent.parent / "assets" / "autosnap.ico",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


class AutoSnapApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()

        self.store = SettingsStore()
        self.settings = self.store.load()
        self.translator = Translator(self.settings.language)
        self.t = self.translator.t

        self.title(self.t("app.title"))
        self.geometry("1060x720")
        self.minsize(860, 560)
        icon = _icon_path()
        if icon:
            try:
                self.iconbitmap(default=str(icon))
            except Exception:
                pass

        self.archive_root = Path(self.settings.archive_dir).expanduser()
        self.archive_root.mkdir(parents=True, exist_ok=True)
        self.db = AutoSnapDB(self.archive_root / "_index" / "autosnap.db")
        self.archiver = Archiver(self.archive_root, self.db)
        self.annotator = AnnotationService(
            api_key=self.settings.openai_api_key or None,
            model=self.settings.openai_model,
        )
        self.watcher: AutoSnapWatcher | None = None
        self.events: queue.Queue[str] = queue.Queue()
        self.thumbnail_refs: list[ImageTk.PhotoImage] = []
        self._row_index: dict[str, dict] = {}
        self._tray: TrayController | None = None

        self._build_ui()
        self.refresh()
        self.after(500, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close_request)

        self._setup_tray()

        if self.settings.start_watching_on_launch:
            self.start_watching()

        if self.settings.start_in_tray and self._tray is not None and self._tray.available:
            self.after(50, self._hide_to_tray)

    # ----- UI construction -----

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = ttk.Frame(self, padding=(12, 10))
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(99, weight=1)

        self.start_btn = ttk.Button(top, text=self.t("btn.start"), command=self.start_watching)
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.stop_btn = ttk.Button(top, text=self.t("btn.stop"), command=self.stop_watching)
        self.stop_btn.grid(row=0, column=1, padx=(0, 6))
        ttk.Button(top, text=self.t("btn.import"), command=self.import_folder).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(top, text=self.t("btn.open_archive"), command=lambda: self._open_path(self.archive_root)).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(top, text=self.t("btn.annotate_backlog"), command=self.annotate_backlog).grid(row=0, column=4, padx=(0, 6))
        ttk.Button(top, text=self.t("btn.settings"), command=self.open_settings).grid(row=0, column=5, padx=(0, 6))
        ttk.Button(top, text=self.t("btn.minimize_to_tray"), command=self._hide_to_tray).grid(row=0, column=6, padx=(0, 6))

        search = ttk.Frame(self, padding=(12, 0, 12, 8))
        search.grid(row=1, column=0, sticky="ew")
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text=self.t("search.label")).grid(row=0, column=0, padx=(0, 8))
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.search_var)
        entry.grid(row=0, column=1, sticky="ew")
        entry.bind("<Return>", lambda _event: self.refresh())
        ttk.Button(search, text=self.t("btn.refresh"), command=self.refresh).grid(row=0, column=2, padx=(8, 0))

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

    # ----- Watching -----

    def start_watching(self) -> None:
        if self.watcher is not None:
            return
        watch_dirs = [Path(item).expanduser() for item in self.settings.watch_dirs]
        if not watch_dirs:
            messagebox.showinfo(self.t("app.title"), self.t("msg.no_watch_dirs"))
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
        self._update_tray_state()
        self.status_var.set(self._status_text(self.t("status.watching")))

    def stop_watching(self) -> None:
        if self.watcher is not None:
            self.watcher.stop()
            self.watcher = None
        self._update_tray_state()
        self.status_var.set(self._status_text(self.t("status.idle")))

    # ----- Import / annotate -----

    def import_folder(self) -> None:
        folder = filedialog.askdirectory(title=self.t("btn.import"))
        if not folder:
            return
        threading.Thread(target=self._import_folder_worker, args=(Path(folder),), daemon=True).start()

    def annotate_backlog(self) -> None:
        if not self.annotator.available:
            messagebox.showinfo(self.t("app.title"), self.t("msg.ai_disabled"))
            return
        threading.Thread(target=self._annotate_backlog_worker, daemon=True).start()

    # ----- Refresh / display -----

    def refresh(self) -> None:
        rows = self.db.search(self.search_var.get(), limit=160)
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.thumbnail_refs.clear()
        self._row_index.clear()

        if not rows:
            ttk.Label(self.grid_frame, text=self.t("empty.hint"), padding=24).grid(row=0, column=0, sticky="w")
            return

        columns = 4
        for idx, row in enumerate(rows):
            row_dict = dict(row)
            self._row_index[row_dict["id"]] = row_dict
            card = ttk.Frame(self.grid_frame, padding=8, relief="ridge")
            card.grid(row=idx // columns, column=idx % columns, sticky="nsew", padx=6, pady=6)
            image_path = self.archive_root / row_dict["archived_path"]
            thumb = self._load_thumbnail(image_path)
            if thumb is not None:
                label = ttk.Label(card, image=thumb)
                label.grid(row=0, column=0, sticky="n")
                self.thumbnail_refs.append(thumb)
                self._bind_card_events(label, row_dict["id"], image_path)
            title = row_dict.get("title") or Path(row_dict["archived_path"]).name
            meta = f"{row_dict.get('category', 'unsorted')} | {self._format_ms(row_dict['captured_at'])}"
            title_lbl = ttk.Label(card, text=title, width=28, wraplength=220)
            title_lbl.grid(row=1, column=0, sticky="w", pady=(6, 0))
            meta_lbl = ttk.Label(card, text=meta, foreground="#555555")
            meta_lbl.grid(row=2, column=0, sticky="w")
            self._bind_card_events(title_lbl, row_dict["id"], image_path)
            self._bind_card_events(meta_lbl, row_dict["id"], image_path)
            self._bind_card_events(card, row_dict["id"], image_path)

    def _bind_card_events(self, widget, screenshot_id: str, image_path: Path) -> None:
        widget.bind("<Double-Button-1>", lambda _e, p=image_path: self._open_path(p))
        widget.bind("<Button-3>", lambda e, sid=screenshot_id, p=image_path: self._show_context_menu(e, sid, p))
        # macOS historical right-click
        widget.bind("<Control-Button-1>", lambda e, sid=screenshot_id, p=image_path: self._show_context_menu(e, sid, p))

    def _show_context_menu(self, event, screenshot_id: str, image_path: Path) -> None:
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label=self.t("menu.copy_image"), command=lambda: self._copy_image(image_path))
        menu.add_command(label=self.t("menu.copy_path"), command=lambda: self._copy_path(image_path))
        menu.add_separator()
        menu.add_command(label=self.t("menu.open_image"), command=lambda: self._open_path(image_path))
        menu.add_command(label=self.t("menu.show_in_folder"), command=lambda: self._show_in_folder(image_path))
        menu.add_separator()
        menu.add_command(label=self.t("menu.toggle_favorite"), command=lambda: self._toggle_favorite(screenshot_id, image_path))
        menu.add_command(label=self.t("menu.delete"), command=lambda: self._delete_screenshot(screenshot_id, image_path))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    def _copy_image(self, image_path: Path) -> None:
        try:
            copy_image_to_clipboard(image_path)
            self.events.put(self.t("msg.copied_image"))
        except NotImplementedError:
            self._copy_path(image_path)
            self.events.put(self.t("msg.copy_image_unsupported"))
        except Exception as exc:
            self.events.put(self.t("msg.copy_image_failed", err=str(exc)))

    def _copy_path(self, image_path: Path) -> None:
        self.clipboard_clear()
        self.clipboard_append(str(image_path))
        self.events.put(self.t("msg.copied_path", path=image_path.name))

    def _show_in_folder(self, image_path: Path) -> None:
        if os.name == "nt":
            try:
                subprocess.run(["explorer", "/select,", str(image_path)])
                return
            except Exception:
                pass
        if platform.system() == "Darwin":
            subprocess.Popen(["open", "-R", str(image_path)])
            return
        self._open_path(image_path.parent)

    def _toggle_favorite(self, screenshot_id: str, image_path: Path) -> None:
        row = self._row_index.get(screenshot_id, {})
        new_value = not bool(row.get("is_favorite", 0))
        self.db.set_favorite(screenshot_id, new_value)
        key = "msg.fav_set" if new_value else "msg.fav_unset"
        self.events.put(self.t(key, name=image_path.name))

    def _delete_screenshot(self, screenshot_id: str, image_path: Path) -> None:
        if not messagebox.askyesno(self.t("app.title"), self.t("msg.confirm_delete")):
            return
        try:
            self.db.delete_screenshot(screenshot_id)
            try:
                image_path.unlink(missing_ok=True)
            except Exception:
                pass
            self.events.put(self.t("msg.deleted", name=image_path.name))
        except Exception as exc:
            self.events.put(self.t("msg.delete_failed", err=str(exc)))

    # ----- Workers -----

    def _import_folder_worker(self, folder: Path) -> None:
        count = 0
        for path in folder.iterdir():
            if not path.is_file():
                continue
            result = self.archiver.archive_file(path, ai_enabled=self.settings.enable_ai and self.annotator.available)
            if result and not result.is_duplicate:
                count += 1
        self.events.put(self.t("msg.imported", count=count, folder=folder))

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
        self.events.put(self.t("msg.ai_done", count=count))

    def _on_archived(self, result: ArchiveResult) -> None:
        if self.settings.enable_ai and self.annotator.available:
            threading.Thread(target=self._annotate_one, args=(result,), daemon=True).start()
        self.events.put(self.t("msg.archived", name=result.archived_path.name))

    def _annotate_one(self, result: ArchiveResult) -> None:
        annotation = self.annotator.annotate(result.archived_path)
        if annotation:
            self.db.add_annotation(result.id, annotation)
            self.events.put(self.t("msg.ai_annotated", name=result.archived_path.name))
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

    # ----- Helpers -----

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
        ai = self.t("status.ai_on") if (self.settings.enable_ai and self.annotator.available) else self.t("status.ai_off")
        watching = self.t("status.watching") if self.watcher else self.t("status.idle")
        dirs = ", ".join(self.settings.watch_dirs) or self.t("status.no_watch")
        parts = [
            watching,
            ai,
            f"{self.t('status.archive_label')}: {self.archive_root}",
            f"{self.t('status.watch_label')}: {dirs}",
        ]
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

    # ----- Tray -----

    def _setup_tray(self) -> None:
        icon = _icon_path()
        if icon is None:
            return
        labels = {
            "show": self.t("tray.show"),
            "start": self.t("tray.start"),
            "stop": self.t("tray.stop"),
            "quit": self.t("tray.quit"),
            "tooltip_idle": self.t("tray.tooltip_idle"),
            "tooltip_watching": self.t("tray.tooltip_watching"),
        }
        tray = TrayController(
            icon_path=icon,
            on_show=lambda: self.after(0, self._show_from_tray),
            on_start=lambda: self.after(0, self.start_watching),
            on_stop=lambda: self.after(0, self.stop_watching),
            on_quit=lambda: self.after(0, self._quit_from_tray),
            labels=labels,
        )
        if not tray.available:
            return
        tray.start()
        self._tray = tray

    def _update_tray_state(self) -> None:
        if self._tray is None:
            return
        self._tray.update_tooltip(self.watcher is not None)

    def _hide_to_tray(self) -> None:
        if self._tray is None or not self._tray.available:
            return
        self.withdraw()
        self.events.put(self.t("msg.tray_running"))

    def _show_from_tray(self) -> None:
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _quit_from_tray(self) -> None:
        # Bypass the close-to-tray hook
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._do_quit()

    def _on_close_request(self) -> None:
        if self.settings.minimize_to_tray_on_close and self._tray is not None and self._tray.available:
            self._hide_to_tray()
            return
        self._do_quit()

    def _do_quit(self) -> None:
        self.stop_watching()
        if self._tray is not None:
            self._tray.stop()
            self._tray = None
        try:
            self.db.close()
        except Exception:
            pass
        self.destroy()

    # ----- Settings dialog -----

    def open_settings(self) -> None:
        SettingsDialog(self)


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: AutoSnapApp) -> None:
        super().__init__(app)
        self.app = app
        self.t = app.t
        self.title(self.t("settings.title"))
        self.geometry("640x520")
        self.transient(app)
        self.grab_set()
        self.resizable(False, False)

        self._build()

    def _build(self) -> None:
        s = self.app.settings
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=(10, 4))

        # ----- General tab -----
        general = ttk.Frame(notebook, padding=12)
        notebook.add(general, text=self.t("settings.tab.general"))
        general.columnconfigure(1, weight=1)

        ttk.Label(general, text=self.t("settings.archive_dir")).grid(row=0, column=0, sticky="w", pady=4)
        self.archive_var = tk.StringVar(value=s.archive_dir)
        ttk.Entry(general, textvariable=self.archive_var).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(general, text=self.t("settings.choose"), command=self._pick_archive).grid(row=0, column=2)
        ttk.Label(general, text=self.t("settings.archive_dir.hint"), foreground="#666").grid(
            row=1, column=0, columnspan=3, sticky="w", pady=(0, 10)
        )

        ttk.Label(general, text=self.t("settings.language")).grid(row=2, column=0, sticky="w", pady=4)
        self.lang_var = tk.StringVar(value=s.language)
        lang_options = [
            (self.t("settings.lang.zh"), "zh_CN"),
            (self.t("settings.lang.en"), "en"),
        ]
        lang_box = ttk.Combobox(
            general,
            state="readonly",
            values=[label for label, _ in lang_options],
        )
        current_label = next((lbl for lbl, code in lang_options if code == s.language), lang_options[0][0])
        lang_box.set(current_label)
        lang_box.grid(row=2, column=1, sticky="w", padx=6)
        self._lang_options = lang_options
        self._lang_box = lang_box

        self.tray_close_var = tk.BooleanVar(value=s.minimize_to_tray_on_close)
        ttk.Checkbutton(general, text=self.t("settings.minimize_to_tray"), variable=self.tray_close_var).grid(
            row=3, column=0, columnspan=3, sticky="w", pady=4
        )
        self.start_in_tray_var = tk.BooleanVar(value=s.start_in_tray)
        ttk.Checkbutton(general, text=self.t("settings.start_in_tray"), variable=self.start_in_tray_var).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=4
        )
        self.start_watching_var = tk.BooleanVar(value=s.start_watching_on_launch)
        ttk.Checkbutton(general, text=self.t("settings.start_watching_on_launch"), variable=self.start_watching_var).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=4
        )

        # ----- Watch tab -----
        watch = ttk.Frame(notebook, padding=12)
        notebook.add(watch, text=self.t("settings.tab.watch"))
        watch.columnconfigure(0, weight=1)
        watch.rowconfigure(1, weight=1)

        ttk.Label(watch, text=self.t("settings.watch_dirs")).grid(row=0, column=0, sticky="w")
        self.dirs_list = tk.Listbox(watch, height=10)
        self.dirs_list.grid(row=1, column=0, sticky="nsew", pady=6)
        for d in s.watch_dirs:
            self.dirs_list.insert("end", d)

        btns = ttk.Frame(watch)
        btns.grid(row=2, column=0, sticky="ew")
        ttk.Button(btns, text=self.t("settings.add_dir"), command=self._add_dir).pack(side="left")
        ttk.Button(btns, text=self.t("settings.remove_dir"), command=self._remove_dir).pack(side="left", padx=6)

        self.enable_clip_var = tk.BooleanVar(value=s.enable_clipboard)
        ttk.Checkbutton(watch, text=self.t("settings.enable_clipboard"), variable=self.enable_clip_var).grid(
            row=3, column=0, sticky="w", pady=(10, 4)
        )

        ttk.Label(watch, text=self.t("settings.poll_interval")).grid(row=4, column=0, sticky="w")
        self.poll_var = tk.DoubleVar(value=s.poll_interval_sec)
        ttk.Spinbox(watch, from_=0.5, to=10.0, increment=0.5, textvariable=self.poll_var, width=8).grid(
            row=5, column=0, sticky="w"
        )

        self.process_existing_var = tk.BooleanVar(value=s.process_existing_on_start)
        ttk.Checkbutton(watch, text=self.t("settings.process_existing"), variable=self.process_existing_var).grid(
            row=6, column=0, sticky="w", pady=(10, 0)
        )

        # ----- AI tab -----
        ai = ttk.Frame(notebook, padding=12)
        notebook.add(ai, text=self.t("settings.tab.ai"))
        ai.columnconfigure(1, weight=1)

        self.enable_ai_var = tk.BooleanVar(value=s.enable_ai)
        ttk.Checkbutton(ai, text=self.t("settings.enable_ai"), variable=self.enable_ai_var).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )

        ttk.Label(ai, text=self.t("settings.openai_key")).grid(row=1, column=0, sticky="w", pady=(10, 4))
        self.api_key_var = tk.StringVar(value=s.openai_api_key)
        ttk.Entry(ai, textvariable=self.api_key_var, show="*").grid(row=1, column=1, sticky="ew", padx=6)
        ttk.Label(ai, text=self.t("settings.openai_key.hint"), foreground="#666").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(0, 10)
        )

        ttk.Label(ai, text=self.t("settings.openai_model")).grid(row=3, column=0, sticky="w", pady=4)
        self.model_var = tk.StringVar(value=s.openai_model)
        ttk.Entry(ai, textvariable=self.model_var).grid(row=3, column=1, sticky="ew", padx=6)

        # ----- Footer -----
        footer = ttk.Frame(self, padding=10)
        footer.pack(fill="x")
        ttk.Button(footer, text=self.t("settings.cancel"), command=self.destroy).pack(side="right", padx=6)
        ttk.Button(footer, text=self.t("settings.save"), command=self._save).pack(side="right")

    def _pick_archive(self) -> None:
        folder = filedialog.askdirectory(parent=self, initialdir=self.archive_var.get() or str(Path.home()))
        if folder:
            self.archive_var.set(folder)

    def _add_dir(self) -> None:
        folder = filedialog.askdirectory(parent=self, initialdir=str(Path.home()))
        if folder:
            self.dirs_list.insert("end", folder)

    def _remove_dir(self) -> None:
        for idx in reversed(self.dirs_list.curselection()):
            self.dirs_list.delete(idx)

    def _save(self) -> None:
        # Resolve language code from selected label
        selected_label = self._lang_box.get()
        language = next(
            (code for label, code in self._lang_options if label == selected_label),
            self.app.settings.language,
        )
        if language not in SUPPORTED_LANGUAGES:
            language = "zh_CN"

        new = Settings(
            archive_dir=self.archive_var.get().strip() or self.app.settings.archive_dir,
            watch_dirs=list(self.dirs_list.get(0, "end")),
            enable_clipboard=bool(self.enable_clip_var.get()),
            keep_originals=self.app.settings.keep_originals,
            enable_ai=bool(self.enable_ai_var.get()),
            openai_api_key=self.api_key_var.get().strip(),
            openai_model=self.model_var.get().strip() or "gpt-4.1-mini",
            poll_interval_sec=float(self.poll_var.get() or 1.5),
            process_existing_on_start=bool(self.process_existing_var.get()),
            language=language,
            minimize_to_tray_on_close=bool(self.tray_close_var.get()),
            start_in_tray=bool(self.start_in_tray_var.get()),
            start_watching_on_launch=bool(self.start_watching_var.get()),
        )
        self.app.store.save(new)
        self.app.settings = new
        # Apply runtime-changeable bits without restart
        self.app.translator.set_language(language)
        self.app.annotator = AnnotationService(
            api_key=new.openai_api_key or None,
            model=new.openai_model,
        )
        if self.app.watcher is not None:
            self.app.stop_watching()
            self.app.start_watching()
        self.app.status_var.set(self.app._status_text())
        messagebox.showinfo(self.t("settings.title"), self.t("settings.saved"), parent=self)
        self.destroy()


def main() -> None:
    app = AutoSnapApp()
    app.mainloop()
