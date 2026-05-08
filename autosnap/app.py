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
from . import theme as theme_mod
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
        self.geometry("1100x740")
        self.minsize(900, 600)
        icon = _icon_path()
        if icon:
            try:
                self.iconbitmap(default=str(icon))
            except Exception:
                pass

        # Apply theme + global font BEFORE building any widgets.
        self.palette = theme_mod.apply(self, self.settings.theme)

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

        # Sidebar / filter state
        self.current_category: str | None = None
        self.favorites_only: bool = False
        self._current_sidebar_key: str = "__all__"
        self._sidebar_buttons: dict[str, tuple] = {}

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
        self.columnconfigure(0, weight=0, minsize=210)  # sidebar
        self.columnconfigure(1, weight=1)               # main content
        self.rowconfigure(3, weight=1)                  # body row stretches

        # ----- Hero / product dashboard (spans both columns) -----
        hero = tk.Frame(
            self,
            background=self.palette["hero_bg"],
            highlightbackground=self.palette["hero_border"],
            highlightthickness=1,
            bd=0,
        )
        hero.grid(row=0, column=0, columnspan=2, sticky="ew", padx=16, pady=(16, 10))
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, weight=0)

        hero_left = tk.Frame(hero, background=self.palette["hero_bg"])
        hero_left.grid(row=0, column=0, sticky="nsew", padx=22, pady=18)

        badge = tk.Label(
            hero_left,
            text=self.t("app.hero_badge"),
            background=self.palette["accent"],
            foreground="#FFFFFF",
            font=theme_mod.font(9, "bold"),
            padx=10,
            pady=4,
        )
        badge.pack(anchor="w", pady=(0, 10))

        tk.Label(
            hero_left,
            text=self.t("app.hero_title"),
            background=self.palette["hero_bg"],
            foreground=self.palette["accent"],
            font=theme_mod.font(25, "bold"),
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            hero_left,
            text=self.t("app.hero_subtitle"),
            background=self.palette["hero_bg"],
            foreground=self.palette["text"],
            font=theme_mod.font(13, "bold"),
            anchor="w",
        ).pack(anchor="w", pady=(6, 12))

        feature_row = tk.Frame(hero_left, background=self.palette["hero_bg"])
        feature_row.pack(anchor="w")
        feature_specs = [
            (self.t("app.value_time"), "⏱", self.palette["accent_soft"], self.palette["accent"]),
            (self.t("app.value_content"), "▤", self.palette["teal_soft"], self.palette["teal"]),
            (self.t("app.value_search"), "⌕", self.palette["purple_soft"], self.palette["purple"]),
            (self.t("app.value_archive"), "▣", self.palette["orange_soft"], self.palette["orange"]),
        ]
        for text, icon_text, bg, fg in feature_specs:
            self._pill(feature_row, f"{icon_text}  {text}", bg, fg).pack(side="left", padx=(0, 8))

        hero_right = tk.Frame(hero, background=self.palette["hero_bg"])
        hero_right.grid(row=0, column=1, sticky="e", padx=(0, 18), pady=16)
        self.stat_total_var = tk.StringVar(value="0")
        self.stat_days_var = tk.StringVar(value="0")
        self.stat_ai_var = tk.StringVar(value="0")
        self.stat_storage_var = tk.StringVar(value="0 B")
        stat_specs = [
            (self.t("stat.total"), self.stat_total_var, self.palette["accent"]),
            (self.t("stat.days"), self.stat_days_var, self.palette["teal"]),
            (self.t("stat.ai"), self.stat_ai_var, self.palette["purple"]),
            (self.t("stat.storage"), self.stat_storage_var, self.palette["orange"]),
        ]
        for idx, (label, var, color) in enumerate(stat_specs):
            self._stat_card(hero_right, label, var, color).grid(
                row=idx // 2, column=idx % 2, padx=5, pady=5, sticky="nsew"
            )

        # ----- Top bar (spans both columns) -----
        top = ttk.Frame(self, padding=(16, 0, 16, 8))
        top.grid(row=1, column=0, columnspan=2, sticky="ew")
        top.columnconfigure(99, weight=1)

        # Primary action gets accent style; everything else stays default.
        self.start_btn = ttk.Button(
            top, text="▶  " + self.t("btn.start"), style="Accent.TButton",
            command=self.start_watching,
        )
        self.start_btn.grid(row=0, column=0, padx=(0, 6))
        self.stop_btn = ttk.Button(top, text="■  " + self.t("btn.stop"), command=self.stop_watching)
        self.stop_btn.grid(row=0, column=1, padx=(0, 14))

        ttk.Button(top, text="📂  " + self.t("btn.import"), command=self.import_folder).grid(row=0, column=2, padx=(0, 6))
        ttk.Button(
            top, text="🗂  " + self.t("btn.open_archive"),
            command=lambda: self._open_path(self.archive_root),
        ).grid(row=0, column=3, padx=(0, 6))
        ttk.Button(
            top, text="✨  " + self.t("btn.annotate_backlog"),
            command=self.annotate_backlog,
        ).grid(row=0, column=4, padx=(0, 14))

        # Right-aligned utility cluster.
        ttk.Button(top, text="⚙  " + self.t("btn.settings"), command=self.open_settings).grid(row=0, column=100, padx=(0, 6))
        ttk.Button(
            top, text="⤓  " + self.t("btn.minimize_to_tray"),
            command=self._hide_to_tray,
        ).grid(row=0, column=101)

        # ----- Sidebar (spans search + body rows) -----
        self.sidebar = self._build_sidebar()
        self.sidebar.grid(row=2, column=0, rowspan=2, sticky="nsew")
        self._refresh_sidebar()

        # ----- Search bar -----
        search = tk.Frame(self, background=self.palette["bg"], bd=0, highlightthickness=0)
        search.grid(row=2, column=1, sticky="ew", padx=16, pady=(0, 8))
        search.columnconfigure(1, weight=1)
        ttk.Label(search, text=self.t("section.quick_filters")).grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.chip_frame = tk.Frame(search, background=self.palette["bg"])
        self.chip_frame.grid(row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 8))

        ttk.Label(search, text="🔍", style="SearchIcon.TLabel").grid(row=1, column=0, padx=(0, 8), sticky="w")
        self.search_var = tk.StringVar()
        entry = ttk.Entry(search, textvariable=self.search_var, font=theme_mod.font(10))
        entry.grid(row=1, column=1, sticky="ew", ipady=5)
        entry.bind("<Return>", lambda _event: self.refresh())
        ttk.Button(search, text=self.t("btn.refresh"), command=self.refresh).grid(row=1, column=2, padx=(10, 0))

        # ----- Body (thumbnail grid) -----
        body = tk.Frame(self, background=self.palette["bg"], bd=0, highlightthickness=0)
        body.grid(row=3, column=1, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.rowconfigure(0, weight=1)

        self.canvas = tk.Canvas(
            body,
            borderwidth=0,
            highlightthickness=0,
            background=self.palette["bg"],
        )
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.grid_frame = tk.Frame(self.canvas, background=self.palette["bg"])
        self.grid_frame.bind("<Configure>", lambda _event: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.grid_frame, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.bind("<Configure>", self._resize_canvas_window)
        self.canvas.grid(row=0, column=0, sticky="nsew", padx=(16, 0))
        scrollbar.grid(row=0, column=1, sticky="ns")

        # Wheel scrolling on the thumbnail grid (Win/Mac/Linux).
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-3, "units"))
        self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(3, "units"))

        # ----- Status bar (spans both columns) -----
        status_bar = tk.Frame(self, background=self.palette["card_bg"], bd=0, highlightthickness=0)
        status_bar.grid(row=4, column=0, columnspan=2, sticky="ew")
        status_bar.columnconfigure(1, weight=1)

        self.status_dot = tk.Label(
            status_bar, text="●", fg=self.palette["idle"],
            background=self.palette["card_bg"], font=theme_mod.font(11),
        )
        self.status_dot.grid(row=0, column=0, sticky="w", padx=(16, 6), pady=6)
        self.status_var = tk.StringVar()
        self.status_var.set(self._status_text())
        status = ttk.Label(status_bar, textvariable=self.status_var, style="Status.TLabel", anchor="w")
        status.grid(row=0, column=1, sticky="ew", padx=(0, 16), pady=6)
        self.status_bar = status_bar

    def _pill(self, parent: tk.Misc, text: str, bg: str, fg: str) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            background=bg,
            foreground=fg,
            font=theme_mod.font(9, "bold"),
            padx=11,
            pady=6,
        )

    def _stat_card(self, parent: tk.Misc, label: str, value: tk.StringVar, color: str) -> tk.Frame:
        card = tk.Frame(
            parent,
            background=self.palette["card_bg"],
            highlightbackground=self.palette["card_border"],
            highlightthickness=1,
            bd=0,
            width=118,
            height=66,
        )
        card.grid_propagate(False)
        tk.Label(
            card,
            text=label,
            background=self.palette["card_bg"],
            foreground=self.palette["text_muted"],
            font=theme_mod.font(8),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(9, 0))
        tk.Label(
            card,
            textvariable=value,
            background=self.palette["card_bg"],
            foreground=color,
            font=theme_mod.font(13, "bold"),
            anchor="w",
        ).pack(anchor="w", padx=10, pady=(2, 0))
        return card

    def _on_mousewheel(self, event) -> None:  # type: ignore[no-untyped-def]
        # Tk on Windows reports delta in multiples of 120; on macOS in units.
        if event.delta == 0:
            return
        step = -1 if event.delta > 0 else 1
        try:
            self.canvas.yview_scroll(step * 3, "units")
        except Exception:
            pass

    # ----- Category sidebar -----

    def _build_sidebar(self) -> tk.Frame:
        sidebar = tk.Frame(
            self,
            background=self.palette["card_bg"],
            highlightbackground=self.palette["card_border"],
            highlightthickness=0,
            bd=0,
            width=210,
        )
        sidebar.grid_propagate(False)

        title = tk.Label(
            sidebar,
            text=self.t("sidebar.title"),
            background=self.palette["card_bg"],
            foreground=self.palette["text_muted"],
            font=theme_mod.font(9, "bold"),
            anchor="w",
        )
        title.pack(fill="x", padx=14, pady=(14, 6))

        self.sidebar_items = tk.Frame(sidebar, background=self.palette["card_bg"])
        self.sidebar_items.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        return sidebar

    def _refresh_sidebar(self) -> None:
        if not hasattr(self, "sidebar_items"):
            return
        for w in self.sidebar_items.winfo_children():
            w.destroy()
        self._sidebar_buttons = {}

        total = self.db.total_count()
        self._add_sidebar_row("__all__", self.t("sidebar.all"), total)

        fav_count = self.db.favorite_count()
        if fav_count > 0:
            self._add_sidebar_row("__favorites__", self.t("sidebar.favorites"), fav_count)

        counts = self.db.category_counts()
        unsorted_pair = next(((c, n) for c, n in counts if c == "unsorted"), None)
        others = [(c, n) for c, n in counts if c != "unsorted"]

        if (others or unsorted_pair) and (fav_count > 0 or others):
            sep = tk.Frame(self.sidebar_items, background=self.palette["card_border"], height=1)
            sep.pack(fill="x", padx=12, pady=6)

        for cat, n in others:
            self._add_sidebar_row(cat, self._category_label(cat), n)

        if unsorted_pair:
            cat, n = unsorted_pair
            if others:
                sep2 = tk.Frame(self.sidebar_items, background=self.palette["card_border"], height=1)
                sep2.pack(fill="x", padx=12, pady=6)
            self._add_sidebar_row(cat, self._category_label(cat), n)

        if total == 0:
            hint = tk.Label(
                self.sidebar_items,
                text=self.t("sidebar.empty_hint"),
                background=self.palette["card_bg"],
                foreground=self.palette["text_muted"],
                font=theme_mod.font(9),
                wraplength=180,
                justify="left",
                anchor="w",
            )
            hint.pack(fill="x", padx=10, pady=(8, 0))

        self._highlight_sidebar()

    def _category_label(self, category: str) -> str:
        label = self.t(f"category.{category}")
        # Translator returns the key itself when missing
        if label.startswith("category."):
            return category
        return label

    def _add_sidebar_row(self, key: str, label: str, count: int) -> None:
        row = tk.Frame(self.sidebar_items, background=self.palette["card_bg"], cursor="hand2")
        row.pack(fill="x", pady=1)
        name_lbl = tk.Label(
            row, text=label,
            background=self.palette["card_bg"],
            foreground=self.palette["text"],
            font=theme_mod.font(10),
            anchor="w",
        )
        name_lbl.pack(side="left", fill="x", expand=True, padx=(10, 6), pady=6)
        count_lbl = tk.Label(
            row, text=str(count),
            background=self.palette["card_bg"],
            foreground=self.palette["text_muted"],
            font=theme_mod.font(9),
        )
        count_lbl.pack(side="right", padx=(0, 10))

        for w in (row, name_lbl, count_lbl):
            w.bind("<Button-1>", lambda _e, k=key: self._select_sidebar(k))
            w.bind("<Enter>", lambda _e, k=key: self._sidebar_hover(k, True))
            w.bind("<Leave>", lambda _e, k=key: self._sidebar_hover(k, False))

        self._sidebar_buttons[key] = (row, name_lbl, count_lbl)

    def _sidebar_hover(self, key: str, hovering: bool) -> None:
        if key == self._current_sidebar_key:
            return
        widgets = self._sidebar_buttons.get(key)
        if not widgets:
            return
        bg = self.palette["bg"] if hovering else self.palette["card_bg"]
        for w in widgets:
            try:
                w.configure(background=bg)
            except Exception:
                pass

    def _select_sidebar(self, key: str) -> None:
        self._current_sidebar_key = key
        if key == "__all__":
            self.current_category = None
            self.favorites_only = False
        elif key == "__favorites__":
            self.current_category = None
            self.favorites_only = True
        else:
            self.current_category = key
            self.favorites_only = False
        self._highlight_sidebar()
        self.refresh(refresh_sidebar=False)

    def _highlight_sidebar(self) -> None:
        accent = self.palette["accent"]
        for k, (row, name_lbl, count_lbl) in self._sidebar_buttons.items():
            selected = (k == self._current_sidebar_key)
            bg = accent if selected else self.palette["card_bg"]
            fg = "#FFFFFF" if selected else self.palette["text"]
            sub = "#E5F0FB" if selected else self.palette["text_muted"]
            for w in (row, name_lbl, count_lbl):
                try:
                    w.configure(background=bg)
                except Exception:
                    pass
            try:
                name_lbl.configure(foreground=fg)
                count_lbl.configure(foreground=sub)
            except Exception:
                pass

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

    def refresh(self, refresh_sidebar: bool = True) -> None:
        if refresh_sidebar:
            self._refresh_sidebar()
        self._update_dashboard_stats()
        self._refresh_filter_chips()
        rows = self.db.search(
            self.search_var.get(),
            limit=160,
            category=self.current_category,
            favorites_only=self.favorites_only,
        )
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self.thumbnail_refs.clear()
        self._row_index.clear()

        if not rows:
            empty = tk.Frame(self.grid_frame, background=self.palette["bg"])
            empty.grid(row=0, column=0, sticky="nsew", padx=40, pady=80)
            tk.Label(
                empty, text="📷", font=theme_mod.font(36),
                background=self.palette["bg"], foreground=self.palette["text_muted"],
            ).pack()
            ttk.Label(empty, text=self.t("empty.hint"), style="EmptyHint.TLabel").pack(pady=(8, 0))
            return

        columns = 4
        for col in range(columns):
            self.grid_frame.columnconfigure(col, weight=1, uniform="cards")

        grid_row = 0
        grid_col = 0
        current_day = None
        for idx, row in enumerate(rows):
            row_dict = dict(row)
            self._row_index[row_dict["id"]] = row_dict
            image_path = self.archive_root / row_dict["archived_path"]
            day_label = self._day_label(row_dict["captured_at"])
            if day_label != current_day:
                if grid_col != 0:
                    grid_row += 1
                    grid_col = 0
                current_day = day_label
                section = tk.Frame(self.grid_frame, background=self.palette["bg"])
                section.grid(row=grid_row, column=0, columnspan=columns, sticky="ew", padx=10, pady=(12, 2))
                section.columnconfigure(1, weight=1)
                tk.Label(
                    section,
                    text=day_label,
                    background=self.palette["bg"],
                    foreground=self.palette["text"],
                    font=theme_mod.font(13, "bold"),
                    anchor="w",
                ).grid(row=0, column=0, sticky="w")
                tk.Frame(section, background=self.palette["card_border"], height=1).grid(
                    row=0, column=1, sticky="ew", padx=(12, 0)
                )
                grid_row += 1

            card = tk.Frame(
                self.grid_frame,
                background=self.palette["card_bg"],
                highlightbackground=self.palette["card_border"],
                highlightthickness=1,
                bd=0,
            )
            card.grid(row=grid_row, column=grid_col, sticky="nsew", padx=10, pady=10)

            inner = tk.Frame(card, background=self.palette["card_bg"])
            inner.pack(fill="both", expand=True, padx=12, pady=12)

            thumb = self._load_thumbnail(image_path)
            if thumb is not None:
                img_label = tk.Label(inner, image=thumb, background=self.palette["card_bg"])
                img_label.pack(anchor="center")
                self.thumbnail_refs.append(thumb)
                self._bind_card_events(img_label, row_dict["id"], image_path)

            title = row_dict.get("title") or Path(row_dict["archived_path"]).name
            category = row_dict.get("category", "unsorted")
            captured = self._format_ms(row_dict["captured_at"])
            category_label = self._category_label(category)

            title_lbl = tk.Label(
                inner, text=title, wraplength=220, justify="left", anchor="w",
                background=self.palette["card_bg"], foreground=self.palette["text"],
                font=theme_mod.font(10, "bold"),
            )
            title_lbl.pack(anchor="w", fill="x", pady=(8, 2))

            meta_row = tk.Frame(inner, background=self.palette["card_bg"])
            meta_row.pack(anchor="w", fill="x")
            cat_lbl = tk.Label(
                meta_row,
                text=category_label,
                background=self.palette["accent_soft"] if category != "unsorted" else self.palette["orange_soft"],
                foreground=self.palette["accent"] if category != "unsorted" else self.palette["orange"],
                font=theme_mod.font(8, "bold"),
                padx=7,
                pady=2,
            )
            cat_lbl.pack(side="left")
            meta_lbl = tk.Label(
                meta_row, text=f"  {captured}",
                background=self.palette["card_bg"], foreground=self.palette["text_muted"],
                font=theme_mod.font(9), anchor="w", justify="left",
            )
            meta_lbl.pack(side="left", fill="x")

            for w in (card, inner, title_lbl, meta_row, cat_lbl, meta_lbl):
                self._bind_card_events(w, row_dict["id"], image_path)
            self._bind_card_hover(card)
            grid_col += 1
            if grid_col >= columns:
                grid_col = 0
                grid_row += 1

    def _update_dashboard_stats(self) -> None:
        if not hasattr(self, "stat_total_var"):
            return
        stats = self.db.dashboard_stats()
        self.stat_total_var.set(str(stats["total"]))
        self.stat_days_var.set(str(stats["active_days"]))
        self.stat_ai_var.set(str(stats["ai_done"]))
        self.stat_storage_var.set(self._format_bytes(stats["bytes_total"]))

    def _refresh_filter_chips(self) -> None:
        if not hasattr(self, "chip_frame"):
            return
        for child in self.chip_frame.winfo_children():
            child.destroy()

        chips: list[tuple[str, str, int | None, str, str]] = [
            ("__all__", self.t("sidebar.all"), self.db.total_count(), self.palette["accent_soft"], self.palette["accent"]),
        ]
        counts = self.db.category_counts()
        color_cycle = [
            (self.palette["teal_soft"], self.palette["teal"]),
            (self.palette["purple_soft"], self.palette["purple"]),
            (self.palette["orange_soft"], self.palette["orange"]),
            (self.palette["accent_soft"], self.palette["accent"]),
        ]
        for idx, (category, count) in enumerate(counts[:6]):
            bg, fg = color_cycle[idx % len(color_cycle)]
            chips.append((category, self._category_label(category), count, bg, fg))

        for key, label, count, bg, fg in chips:
            text = f"{label}  {count}" if count is not None else label
            active = key == self._current_sidebar_key
            chip = tk.Label(
                self.chip_frame,
                text=text,
                background=self.palette["accent"] if active else bg,
                foreground="#FFFFFF" if active else fg,
                font=theme_mod.font(9, "bold"),
                padx=11,
                pady=5,
                cursor="hand2",
            )
            chip.pack(side="left", padx=(0, 8), pady=(0, 4))
            chip.bind("<Button-1>", lambda _e, k=key: self._select_sidebar(k))

    def _bind_card_events(self, widget, screenshot_id: str, image_path: Path) -> None:
        widget.bind("<Double-Button-1>", lambda _e, p=image_path: self._open_path(p))
        widget.bind("<Button-3>", lambda e, sid=screenshot_id, p=image_path: self._show_context_menu(e, sid, p))
        # macOS historical right-click
        widget.bind("<Control-Button-1>", lambda e, sid=screenshot_id, p=image_path: self._show_context_menu(e, sid, p))

    def _bind_card_hover(self, card: tk.Frame) -> None:
        normal = self.palette["card_border"]
        hover = self.palette["accent"]

        def on_enter(_e):
            try:
                card.configure(highlightbackground=hover)
            except Exception:
                pass

        def on_leave(_e):
            try:
                card.configure(highlightbackground=normal)
            except Exception:
                pass

        card.bind("<Enter>", on_enter)
        card.bind("<Leave>", on_leave)

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
        # Reflect watching state via the ● color in the status bar.
        if hasattr(self, "status_dot") and self.status_dot is not None:
            try:
                color = self.palette["ok"] if self.watcher else self.palette["idle"]
                self.status_dot.configure(fg=color)
            except Exception:
                pass
        return "  ·  ".join(parts)

    @staticmethod
    def _format_ms(value: int) -> str:
        import datetime as _dt

        return _dt.datetime.fromtimestamp(value / 1000).strftime("%Y-%m-%d %H:%M:%S")

    def _day_label(self, value: int) -> str:
        import datetime as _dt

        day = _dt.datetime.fromtimestamp(value / 1000).date()
        today = _dt.date.today()
        if day == today:
            prefix = "今天" if self.settings.language == "zh_CN" else "Today"
        elif day == today - _dt.timedelta(days=1):
            prefix = "昨天" if self.settings.language == "zh_CN" else "Yesterday"
        else:
            prefix = day.strftime("%Y-%m-%d")
        return f"{prefix} · {day:%m/%d}"

    @staticmethod
    def _format_bytes(value: int) -> str:
        units = ["B", "KB", "MB", "GB", "TB"]
        amount = float(value)
        for unit in units:
            if amount < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(amount)} {unit}"
                return f"{amount:.1f} {unit}"
            amount /= 1024

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

        ttk.Label(general, text=self.t("settings.theme")).grid(row=3, column=0, sticky="w", pady=4)
        theme_options = [
            (self.t("settings.theme.light"), "light"),
            (self.t("settings.theme.dark"), "dark"),
        ]
        theme_box = ttk.Combobox(
            general,
            state="readonly",
            values=[label for label, _ in theme_options],
        )
        current_theme_label = next(
            (lbl for lbl, code in theme_options if code == s.theme), theme_options[0][0]
        )
        theme_box.set(current_theme_label)
        theme_box.grid(row=3, column=1, sticky="w", padx=6)
        self._theme_options = theme_options
        self._theme_box = theme_box

        self.tray_close_var = tk.BooleanVar(value=s.minimize_to_tray_on_close)
        ttk.Checkbutton(general, text=self.t("settings.minimize_to_tray"), variable=self.tray_close_var).grid(
            row=4, column=0, columnspan=3, sticky="w", pady=4
        )
        self.start_in_tray_var = tk.BooleanVar(value=s.start_in_tray)
        ttk.Checkbutton(general, text=self.t("settings.start_in_tray"), variable=self.start_in_tray_var).grid(
            row=5, column=0, columnspan=3, sticky="w", pady=4
        )
        self.start_watching_var = tk.BooleanVar(value=s.start_watching_on_launch)
        ttk.Checkbutton(general, text=self.t("settings.start_watching_on_launch"), variable=self.start_watching_var).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=4
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

        # Resolve theme code
        theme_label = self._theme_box.get()
        theme = next(
            (code for label, code in self._theme_options if label == theme_label),
            self.app.settings.theme,
        )
        if theme not in ("light", "dark"):
            theme = "light"

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
            theme=theme,
            minimize_to_tray_on_close=bool(self.tray_close_var.get()),
            start_in_tray=bool(self.start_in_tray_var.get()),
            start_watching_on_launch=bool(self.start_watching_var.get()),
        )
        self.app.store.save(new)
        self.app.settings = new
        # Apply runtime-changeable bits without restart
        self.app.translator.set_language(language)
        if theme != self.app.palette and theme in ("light", "dark"):
            try:
                self.app.palette = theme_mod.apply(self.app, theme)
                self.app.refresh()
            except Exception:
                pass
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
