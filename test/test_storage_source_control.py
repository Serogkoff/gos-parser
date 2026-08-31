import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import storage
from utils.source_groups import GOVERNMENT_GROUP


class SourceControlStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.patchers = (
            patch.object(storage, "DATABASE_FILE", directory / "news.db"),
            patch.object(storage, "ALL_NEWS_FILE", directory / "all_news.json"),
            patch.object(storage, "FOUND_NEWS_FILE", directory / "found_news.json"),
            patch.object(storage, "BACKUP_DIR", directory / "backups"),
        )
        for patcher in self.patchers:
            patcher.start()
        self.owner = storage.create_user(
            "owner", "owner-secret-2026", role="admin"
        )

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        gc.collect()
        self.temporary.cleanup()

    def test_source_order_is_cleaned_and_deduplicated(self):
        saved = storage.save_source_order(
            self.owner["id"],
            GOVERNMENT_GROUP,
            [" МЧС ", "мчс", "", "Правительство РФ"],
        )

        self.assertEqual(saved, ["МЧС", "Правительство РФ"])
        self.assertEqual(
            storage.load_source_order(self.owner["id"], GOVERNMENT_GROUP),
            saved,
        )

    def test_source_pause_is_persisted(self):
        storage.set_source_enabled(" МЧС ", False)

        self.assertFalse(storage.source_is_enabled("МЧС"))
        self.assertFalse(storage.load_source_settings()["МЧС"]["enabled"])

    def test_stale_job_is_closed_before_next_job_is_claimed(self):
        first = storage.enqueue_parser_job("МЧС", self.owner["id"])
        claimed = storage.claim_next_parser_job()
        self.assertEqual(claimed["id"], first["id"])
        with storage._connection() as connection:
            connection.execute(
                "UPDATE parser_jobs SET started_at = ? WHERE id = ?",
                ("2020-01-01T00:00:00", first["id"]),
            )

        second = storage.enqueue_parser_job("МИД РФ", self.owner["id"])
        next_job = storage.claim_next_parser_job()
        self.assertEqual(next_job["id"], second["id"])
        jobs = {item["id"]: item for item in storage.list_parser_jobs()}
        self.assertEqual(jobs[first["id"]]["status"], "error")
        self.assertIn("перезапущен", jobs[first["id"]]["error"])

        storage.finish_parser_job(second["id"], True)
        with self.assertRaisesRegex(ValueError, "уже завершено"):
            storage.finish_parser_job(second["id"], True)


if __name__ == "__main__":
    unittest.main()
