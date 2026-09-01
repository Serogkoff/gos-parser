import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from utils import storage


class NewsPersistenceStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database = directory / "news.db"
        self.patchers = (
            patch.object(storage, "DATABASE_FILE", self.database),
            patch.object(storage, "ALL_NEWS_FILE", directory / "all_news.json"),
            patch.object(
                storage,
                "FOUND_NEWS_FILE",
                directory / "found_news.json",
            ),
        )
        for patcher in self.patchers:
            patcher.start()
        storage.initialize_database()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    @staticmethod
    def _item(number, **fields):
        return {
            "source": "Тестовый источник",
            "title": f"Новость {number}",
            "url": f"https://example.test/news/{number}",
            "date": "2026-09-01",
            **fields,
        }

    def test_concurrent_saves_do_not_lose_news(self):
        items = [self._item(1), self._item(2)]

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda item: storage.save_results([item], [], set()),
                    items,
                )
            )

        self.assertEqual(results, [[], []])
        self.assertEqual(
            {item["url"] for item in storage.load_all_news()},
            {item["url"] for item in items},
        )

    def test_replacing_collection_keeps_first_seen_timestamp(self):
        item = self._item(1, summary="Первая версия")
        storage.save_results([item], [], set())
        with storage._connection() as connection:
            first_seen = connection.execute(
                "SELECT first_seen_at FROM news_items"
            ).fetchone()["first_seen_at"]

        updated = {**item, "summary": "Обновлённая версия"}
        storage.save_results(
            [updated],
            [],
            storage.load_existing_urls(),
        )

        with storage._connection() as connection:
            row = connection.execute(
                "SELECT first_seen_at, payload_json FROM news_items"
            ).fetchone()
        self.assertEqual(row["first_seen_at"], first_seen)
        self.assertEqual(
            json.loads(row["payload_json"])["summary"],
            "Обновлённая версия",
        )

    def test_replacement_discards_orphaned_found_item(self):
        available = self._item(1)
        orphaned = self._item(2, keywords=["тест"])

        with storage._connection() as connection:
            storage._replace_collections(
                connection,
                [available],
                [orphaned],
            )

        self.assertEqual(storage.load_found_news(), [])
        self.assertEqual(len(storage.load_all_news()), 1)

    def test_article_cache_deduplicates_and_limits_text(self):
        first = "А" * 60_000
        second = "Б" * 60_000

        saved = storage.save_cached_article(
            "https://example.test/article/large",
            {
                "title": "  Большая   статья  ",
                "paragraphs": [first, first, second],
                "error": "",
            },
            "Тестовый источник",
        )

        self.assertEqual(saved["title"], "Большая статья")
        self.assertEqual(len(saved["paragraphs"]), 2)
        self.assertEqual(
            sum(len(item) for item in saved["paragraphs"]),
            storage.MAX_CACHED_ARTICLE_CHARS,
        )


if __name__ == "__main__":
    unittest.main()
