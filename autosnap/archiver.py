from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

from PIL import Image, ImageOps

from .db import AutoSnapDB
from .models import ArchiveResult, IMAGE_EXTENSIONS


class Archiver:
    def __init__(self, archive_root: Path, db: AutoSnapDB) -> None:
        self.archive_root = archive_root
        self.db = db
        self.archive_root.mkdir(parents=True, exist_ok=True)
        (self.archive_root / "_index").mkdir(exist_ok=True)
        (self.archive_root / "_cache" / "thumbs").mkdir(parents=True, exist_ok=True)

    def archive_file(self, path: Path, source: str = "file", ai_enabled: bool = False) -> ArchiveResult | None:
        path = path.expanduser().resolve()
        if path.suffix.lower() not in IMAGE_EXTENSIONS:
            return None
        if not path.exists() or not path.is_file():
            return None
        self._wait_until_stable(path)

        sha = self._sha256_path(path)
        existing = self.db.get_by_sha(sha)
        if existing:
            return ArchiveResult(
                id=existing["id"],
                sha256=sha,
                archived_path=self.archive_root / existing["archived_path"],
                relative_path=existing["archived_path"],
                original_path=str(path),
                captured_at_ms=existing["captured_at"],
                width=existing["width"],
                height=existing["height"],
                bytes=existing["bytes"],
                image_format=existing["format"],
                category=existing["category"],
                is_duplicate=True,
            )

        captured_at_ms = int(path.stat().st_mtime * 1000)
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image)
            width, height = image.size
            image_format = (image.format or path.suffix.lstrip(".") or "png").lower()

        dest = self._destination_path(captured_at_ms, "unsorted", sha, path.suffix.lower() or ".png")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        if self._sha256_path(dest) != sha:
            dest.unlink(missing_ok=True)
            raise IOError(f"Archive verification failed for {path}")

        result = ArchiveResult(
            id=self._make_id(captured_at_ms, sha),
            sha256=sha,
            archived_path=dest,
            relative_path=str(dest.relative_to(self.archive_root)).replace(os.sep, "/"),
            original_path=str(path),
            captured_at_ms=captured_at_ms,
            width=width,
            height=height,
            bytes=dest.stat().st_size,
            image_format=image_format,
            category="unsorted",
        )
        inserted = self.db.add_screenshot(result, source=source, platform_name=platform.system().lower(), ai_enabled=ai_enabled)
        if inserted:
            self._write_meta(result, source)
            self.ensure_thumbnail(result.archived_path)
        return result

    def archive_clipboard_image(self, image: Image.Image, ai_enabled: bool = False) -> ArchiveResult | None:
        now_ms = int(time.time() * 1000)
        tmp_dir = self.archive_root / "_inbox"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = tmp_dir / f"clipboard_{now_ms}.png"
        image = ImageOps.exif_transpose(image.convert("RGBA"))
        image.save(tmp_path, format="PNG")
        try:
            result = self.archive_file(tmp_path, source="clipboard", ai_enabled=ai_enabled)
            if result is not None:
                self.db.conn.execute("UPDATE screenshots SET original_path = NULL WHERE id = ?", (result.id,))
                self.db.conn.commit()
                result = replace(result, original_path=None)
            return result
        finally:
            tmp_path.unlink(missing_ok=True)

    def ensure_thumbnail(self, image_path: Path) -> Path | None:
        try:
            rel = image_path.relative_to(self.archive_root)
        except ValueError:
            rel = image_path.name
        thumb_name = hashlib.sha256(str(rel).encode("utf-8")).hexdigest()[:16] + ".jpg"
        thumb_path = self.archive_root / "_cache" / "thumbs" / thumb_name
        if thumb_path.exists():
            return thumb_path

        try:
            with Image.open(image_path) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((256, 256))
                rgb = image.convert("RGB")
                rgb.save(thumb_path, "JPEG", quality=82)
            return thumb_path
        except Exception:
            return None

    def _destination_path(self, captured_at_ms: int, category: str, sha: str, suffix: str) -> Path:
        dt = datetime.fromtimestamp(captured_at_ms / 1000)
        safe_suffix = suffix if suffix.lower() in IMAGE_EXTENSIONS else ".png"
        filename = f"{dt:%Y-%m-%d_%H-%M-%S}_{category}_{sha[:8]}{safe_suffix}"
        return self.archive_root / f"{dt:%Y}" / f"{dt:%m}" / f"{dt:%d}" / filename

    def _write_meta(self, result: ArchiveResult, source: str) -> None:
        meta_dir = result.archived_path.parent / ".meta"
        meta_dir.mkdir(exist_ok=True)
        meta = {
            "id": result.id,
            "sha256": result.sha256,
            "archived_path": result.relative_path,
            "original_path": result.original_path,
            "captured_at": result.captured_at_ms,
            "width": result.width,
            "height": result.height,
            "bytes": result.bytes,
            "format": result.image_format,
            "category": result.category,
            "source": source,
        }
        (meta_dir / f"{result.archived_path.stem}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @staticmethod
    def _sha256_path(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as fh:
            Archiver._update_hash(fh, digest)
        return digest.hexdigest()

    @staticmethod
    def _update_hash(fh: BinaryIO, digest: "hashlib._Hash") -> None:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)

    @staticmethod
    def _make_id(captured_at_ms: int, sha: str) -> str:
        return f"{captured_at_ms:x}-{sha[:12]}"

    @staticmethod
    def _wait_until_stable(path: Path, timeout: float = 5.0) -> None:
        deadline = time.time() + timeout
        previous = (-1, -1)
        while time.time() < deadline:
            try:
                stat = path.stat()
            except FileNotFoundError:
                time.sleep(0.1)
                continue
            current = (stat.st_size, int(stat.st_mtime_ns))
            if current == previous and stat.st_size > 0:
                return
            previous = current
            time.sleep(0.2)
