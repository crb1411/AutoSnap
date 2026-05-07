from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from autosnap.archiver import Archiver
from autosnap.db import AutoSnapDB


class ArchiverTests(unittest.TestCase):
    def test_archive_file_deduplicates_and_searches(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source.png"
            Image.new("RGB", (64, 32), color=(20, 80, 120)).save(source)

            db = AutoSnapDB(root / "archive" / "_index" / "autosnap.db")
            archiver = Archiver(root / "archive", db)

            first = archiver.archive_file(source)
            self.assertIsNotNone(first)
            assert first is not None
            self.assertTrue(first.archived_path.exists())
            self.assertIn("_unsorted_", first.relative_path)

            second = archiver.archive_file(source)
            self.assertIsNotNone(second)
            assert second is not None
            self.assertTrue(second.is_duplicate)
            self.assertEqual(first.sha256, second.sha256)

            rows = db.search("unsorted")
            self.assertEqual(len(rows), 1)
            db.close()


if __name__ == "__main__":
    unittest.main()
