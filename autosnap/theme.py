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
    "bg": "#F6F9FE",
    "card_bg": "#FFFFFF",
    "card_border": "#DDE8F6",
    "hero_bg": "#EAF4FF",
    "hero_border": "#C8DBF5",
    "text": "#102033",
    "text_muted": "#61708A",
    "accent": "#1463E6",
    "accent_soft": "#E7F0FF",
    "teal": "#19A88B",
    "teal_soft": "#E7F8F5",
    "orange": "#F59E42",
    "orange_soft": "#FFF3E7",
    "purple": "#7C5CFF",
    "purple_soft": "#F0EDFF",
    "ok": "#1F8B4C",
    "idle": "#9C9C9C",
}

DARK = {
    "bg": "#1F1F1F",
    "card_bg": "#2B2B2B",
    "card_border": "#3A3A3A",
    "hero_bg": "#243247",
    "hero_border": "#3A557A",
    "text": "#EFEFEF",
    "text_muted": "#A0A0A0",
    "accent": "#4CC2FF",
    "accent_soft": "#1E3442",
    "teal": "#4CD7B0",
    "teal_soft": "#18372F",
    "orange": "#FFB15C",
    "orange_soft": "#3F2A18",
    "purple": "#A99BFF",
    "purple_soft": "#312A4A",
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
