"""Centralized look-and-feel: fonts, colors, and ttk style configuration.

We try sv_ttk for a Windows 11-like Sun Valley theme. If unavailable we
fall back to the best built-in ttk theme on the platform, plus our own
color tweaks so the app still looks deliberate rather than 1995-era Tk.
"""
from __future__ import annotations

import platform
import tkinter as tk
from tkinter import ttk
from typing import Tuple

try:
    import sv_ttk
    _HAS_SV_TTK = True
except Exception:  # pragma: no cover
    sv_ttk = None  # type: ignore
    _HAS_SV_TTK = False


# Color palette (light)
LIGHT = {
    "bg": "#FAFAFA",
    "card_bg": "#FFFFFF",
    "card_border": "#E5E5E5",
    "text": "#1F1F1F",
    "text_muted": "#6B6B6B",
    "accent": "#0067C0",
    "ok": "#1F8B4C",
    "idle": "#9C9C9C",
}

DARK = {
    "bg": "#1F1F1F",
    "card_bg": "#2B2B2B",
    "card_border": "#3A3A3A",
    "text": "#EFEFEF",
    "text_muted": "#A0A0A0",
    "accent": "#4CC2FF",
    "ok": "#4CD787",
    "idle": "#7A7A7A",
}


def palette(theme: str) -> dict:
    return DARK if theme == "dark" else LIGHT


def default_font_family() -> str:
    system = platform.system()
    if system == "Windows":
        return "Microsoft YaHei UI"
    if system == "Darwin":
        return "PingFang SC"
    return "Noto Sans CJK SC"


def font(size: int = 10, weight: str = "normal") -> Tuple[str, int, str]:
    return (default_font_family(), size, weight)


def apply(root: tk.Tk, theme: str = "light") -> dict:
    """Apply theme + custom styles. Returns the active palette dict."""
    pal = palette(theme)

    if _HAS_SV_TTK:
        try:
            sv_ttk.set_theme("dark" if theme == "dark" else "light")
        except Exception:
            pass
    else:
        style = ttk.Style(root)
        for candidate in ("vista", "xpnative", "clam", "alt"):
            if candidate in style.theme_names():
                style.theme_use(candidate)
                break

    style = ttk.Style(root)

    # Base font for all ttk widgets
    base = font(10)
    style.configure(".", font=base)

    # Top-bar buttons
    style.configure("TButton", padding=(12, 6))
    # sv_ttk already provides "Accent.TButton"; this keeps it sane on fallback.
    style.configure("Accent.TButton", padding=(14, 6))

    # Card frame and labels (we render cards via tk.Frame to get bg color
    # control, since ttk.Frame ignores `background` on most themes).
    style.configure(
        "CardTitle.TLabel",
        font=font(10, "bold"),
        foreground=pal["text"],
    )
    style.configure(
        "CardMeta.TLabel",
        font=font(9),
        foreground=pal["text_muted"],
    )
    style.configure(
        "Status.TLabel",
        font=font(9),
        foreground=pal["text_muted"],
    )
    style.configure(
        "EmptyHint.TLabel",
        font=font(11),
        foreground=pal["text_muted"],
    )
    style.configure(
        "SectionHint.TLabel",
        font=font(9),
        foreground=pal["text_muted"],
    )
    style.configure(
        "SearchIcon.TLabel",
        font=font(11),
        foreground=pal["text_muted"],
    )

    # Match the Tk root background to the theme so any non-ttk widgets blend.
    try:
        root.configure(background=pal["bg"])
    except Exception:
        pass

    return pal


def has_sv_ttk() -> bool:
    return _HAS_SV_TTK
