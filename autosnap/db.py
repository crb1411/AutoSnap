from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Iterable

from .models import Annotation, ArchiveResult


SCHEMA_VERSION = 1


class AutoSnapDB:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._fts_available = True
        self.init()

    def init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS screenshots (
              id TEXT PRIMARY KEY,
              sha256 TEXT NOT NULL UNIQUE,
              archived_path TEXT NOT NULL,
              original_path TEXT,
              captured_at INTEGER NOT NULL,
              archived_at INTEGER NOT NULL,
              width INTEGER NOT NULL,
              height INTEGER NOT NULL,
              bytes INTEGER NOT NULL,
              format TEXT NOT NULL,
              source TEXT NOT NULL,
              platform TEXT NOT NULL,
              category TEXT NOT NULL DEFAULT 'unsorted',
              is_favorite INTEGER NOT NULL DEFAULT 0,
              ai_status TEXT NOT NULL DEFAULT 'skipped',
              deleted_at INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_screenshots_captured_at
              ON screenshots(captured_at DESC);

            CREATE INDEX IF NOT EXISTS idx_screenshots_category
              ON screenshots(category);

            CREATE TABLE IF NOT EXISTS annotations (
              screenshot_id TEXT PRIMARY KEY REFERENCES screenshots(id) ON DELETE CASCADE,
              category TEXT NOT NULL,
              title TEXT,
              summary TEXT,
              tags_json TEXT NOT NULL,
              ocr_text TEXT,
              has_sensitive INTEGER NOT NULL DEFAULT 0,
              sensitive_types_json TEXT NOT NULL,
              confidence REAL NOT NULL DEFAULT 0,
              model TEXT NOT NULL,
              annotated_at INTEGER NOT NULL
            );
            """
        )
        self.conn.execute(
            "INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', ?)",
            (str(SCHEMA_VERSION),),
        )
        try:
            self.conn.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
                  screenshot_id UNINDEXED,
                  content,
                  tokenize='unicode61'
                )
                """
            )
        except sqlite3.OperationalError:
            self._fts_available = False
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def add_screenshot(self, item: ArchiveResult, source: str, platform_name: str, ai_enabled: bool) -> bool:
        ai_status = "pending" if ai_enabled else "skipped"
        try:
            self.conn.execute(
                """
                INSERT INTO screenshots(
                  id, sha256, archived_path, original_path, captured_at, archived_at,
                  width, height, bytes, format, source, platform, category, ai_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.id,
                    item.sha256,
                    item.relative_path,
                    item.original_path,
                    item.captured_at_ms,
                    int(time.time() * 1000),
                    item.width,
                    item.height,
                    item.bytes,
                    item.image_format,
                    source,
                    platform_name,
                    item.category,
                    ai_status,
                ),
            )
            self._upsert_fts(item.id, self._base_search_text(item))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def get_by_sha(self, sha256: str) -> sqlite3.Row | None:
        cur = self.conn.execute("SELECT * FROM screenshots WHERE sha256 = ?", (sha256,))
        return cur.fetchone()

    def latest(self, limit: int = 120) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT s.*, a.title, a.summary, a.tags_json, a.ocr_text
            FROM screenshots s
            LEFT JOIN annotations a ON a.screenshot_id = s.id
            WHERE s.deleted_at IS NULL
            ORDER BY s.captured_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def search(self, keyword: str, limit: int = 120) -> list[sqlite3.Row]:
        keyword = keyword.strip()
        if not keyword:
            return self.latest(limit)

        if self._fts_available:
            try:
                cur = self.conn.execute(
                    """
                    SELECT s.*, a.title, a.summary, a.tags_json, a.ocr_text
                    FROM search_fts f
                    JOIN screenshots s ON s.id = f.screenshot_id
                    LEFT JOIN annotations a ON a.screenshot_id = s.id
                    WHERE search_fts MATCH ? AND s.deleted_at IS NULL
                    ORDER BY bm25(search_fts), s.captured_at DESC
                    LIMIT ?
                    """,
                    (self._fts_query(keyword), limit),
                )
                return list(cur.fetchall())
            except sqlite3.OperationalError:
                pass

        like = f"%{keyword}%"
        cur = self.conn.execute(
            """
            SELECT s.*, a.title, a.summary, a.tags_json, a.ocr_text
            FROM screenshots s
            LEFT JOIN annotations a ON a.screenshot_id = s.id
            WHERE s.deleted_at IS NULL
              AND (
                s.archived_path LIKE ?
                OR s.category LIKE ?
                OR COALESCE(a.title, '') LIKE ?
                OR COALESCE(a.summary, '') LIKE ?
                OR COALESCE(a.ocr_text, '') LIKE ?
                OR COALESCE(a.tags_json, '') LIKE ?
              )
            ORDER BY s.captured_at DESC
            LIMIT ?
            """,
            (like, like, like, like, like, like, limit),
        )
        return list(cur.fetchall())

    def add_annotation(self, screenshot_id: str, annotation: Annotation) -> None:
        now = int(time.time() * 1000)
        self.conn.execute(
            """
            INSERT OR REPLACE INTO annotations(
              screenshot_id, category, title, summary, tags_json, ocr_text,
              has_sensitive, sensitive_types_json, confidence, model, annotated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                screenshot_id,
                annotation.category,
                annotation.title,
                annotation.summary,
                json.dumps(annotation.tags, ensure_ascii=False),
                annotation.ocr_text,
                1 if annotation.has_sensitive_info else 0,
                json.dumps(annotation.sensitive_types, ensure_ascii=False),
                annotation.confidence,
                annotation.model,
                now,
            ),
        )
        self.conn.execute(
            "UPDATE screenshots SET category = ?, ai_status = 'done' WHERE id = ?",
            (annotation.category, screenshot_id),
        )
        self._upsert_fts(
            screenshot_id,
            " ".join(
                [
                    annotation.category,
                    annotation.title,
                    annotation.summary,
                    " ".join(annotation.tags),
                    annotation.ocr_text,
                ]
            ),
        )
        self.conn.commit()

    def mark_ai_failed(self, screenshot_id: str) -> None:
        self.conn.execute("UPDATE screenshots SET ai_status = 'failed' WHERE id = ?", (screenshot_id,))
        self.conn.commit()

    def pending_ai(self, limit: int = 20) -> list[sqlite3.Row]:
        cur = self.conn.execute(
            """
            SELECT * FROM screenshots
            WHERE ai_status IN ('pending', 'failed') AND deleted_at IS NULL
            ORDER BY captured_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return list(cur.fetchall())

    def _upsert_fts(self, screenshot_id: str, content: str) -> None:
        if not self._fts_available:
            return
        self.conn.execute("DELETE FROM search_fts WHERE screenshot_id = ?", (screenshot_id,))
        self.conn.execute(
            "INSERT INTO search_fts(screenshot_id, content) VALUES (?, ?)",
            (screenshot_id, content),
        )

    @staticmethod
    def _base_search_text(item: ArchiveResult) -> str:
        return f"{item.relative_path} {item.category} {item.image_format}"

    @staticmethod
    def _fts_query(keyword: str) -> str:
        tokens = [token for token in keyword.replace('"', " ").split() if token]
        return " OR ".join(tokens) if tokens else keyword


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
