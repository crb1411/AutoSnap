from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional


CATEGORIES = [
    "chat",
    "web",
    "code",
    "terminal",
    "error",
    "design",
    "form",
    "receipt",
    "map",
    "video",
    "table",
    "qr",
    "id_doc",
    "social",
    "email",
    "slide",
    "misc",
    "unsorted",
]


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


@dataclass(frozen=True)
class ArchiveResult:
    id: str
    sha256: str
    archived_path: Path
    relative_path: str
    original_path: Optional[str]
    captured_at_ms: int
    width: int
    height: int
    bytes: int
    image_format: str
    category: str
    is_duplicate: bool = False


@dataclass(frozen=True)
class Annotation:
    category: str
    title: str
    summary: str
    tags: list[str]
    ocr_text: str
    has_sensitive_info: bool
    sensitive_types: list[str]
    confidence: float
    model: str
