import json
import sqlite3
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from threading import RLock
from unittest import mock

from utils import storage
from utils.news import deduplicate_news
from utils.storage_initialization import DatabaseInitializer
from utils.storage_schema import create_schema


class StorageInitializationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database = directory / "news.db"
        self.all_news = directory / "all_news.json"
        self.found_news = directory / "found_news.json"
        self.logger = mock.Mock()

    def tearDown(self):
        self.temporary.cleanup()

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.database, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _stats(self, connection):
        return {
            "news_count": connection.execute(
                "SELECT COUNT(*) FROM news_items"
            ).fetchone()[0],
            "found_count": connection.execute(
                "SELECT COUNT(*) FROM found_items"
            ).fetchone()[0],
            "integrity": connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0],
        }

    def _initializer(self, lock=None):
        return DatabaseInitializer(
            database_file=lambda: self.database,
            all_news_file=lambda: self.all_news,
            found_news_file=lambda: self.found_news,
            connection_factory=self._connection,
            create_schema=create_schema,
            database_stats=self._stats,
            replace_collections=storage._replace_collections,
            deduplicate_news=deduplicate_news,
            news_key=storage._news_key,
            lock=lock or RLock(),
            migration_key="json_migration_v1",
            logger=self.logger,
            now=lambda: datetime(2026, 9, 1, 12, 0, 0),
        )

    def _write_json(self, path, items):
        path.write_text(
            json.dumps(items, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_first_start_imports_found_only_item_without_keywords_in_feed(self):
        found = {
            "source": "МИД РФ",
            "title": "Заявление Министерства иностранных дел",
            "url": "https://mid.ru/ru/foreign_policy/news/first-start",
            "date": "2026-09-01",
            "keywords": ["Япония"],
        }
        self._write_json(self.all_news, [])
        self._write_json(self.found_news, [found])

        stats = self._initializer().initialize_database()

        self.assertEqual(stats["news_count"], 1)
        self.assertEqual(stats["found_count"], 1)
        self.assertEqual(stats["integrity"], "ok")
        with self._connection() as connection:
            news_payload = json.loads(connection.execute(
                "SELECT payload_json FROM news_items"
            ).fetchone()[0])
            found_payload = json.loads(connection.execute(
                "SELECT payload_json FROM found_items"
            ).fetchone()[0])
            migration = json.loads(connection.execute(
                "SELECT value FROM metadata WHERE key = 'json_migration_v1'"
            ).fetchone()[0])

        self.assertNotIn("keywords", news_payload)
        self.assertEqual(found_payload["keywords"], ["Япония"])
        self.assertEqual(migration["all_news"], 1)
        self.assertEqual(migration["found_news"], 1)
        self.assertTrue(self.all_news.exists())
        self.assertTrue(self.found_news.exists())

    def test_restart_does_not_import_changed_json_again(self):
        first = {
            "source": "МЧС",
            "title": "Первая публикация",
            "url": "https://mchs.gov.ru/news/first",
        }
        second = {
            "source": "МЧС",
            "title": "Вторая публикация",
            "url": "https://mchs.gov.ru/news/second",
        }
        self._write_json(self.all_news, [first])
        self._write_json(self.found_news, [])
        self._initializer().initialize_database()
        self._write_json(self.all_news, [second])

        stats = self._initializer().initialize_database()

        self.assertEqual(stats["news_count"], 1)
        with self._connection() as connection:
            title = connection.execute(
                "SELECT title FROM news_items"
            ).fetchone()[0]
        self.assertEqual(title, first["title"])

    def test_separate_initializers_serialize_first_migration(self):
        item = {
            "source": "МИД РФ",
            "title": "Параллельная инициализация",
            "url": "https://mid.ru/ru/news/concurrent-start",
        }
        self._write_json(self.all_news, [item])
        self._write_json(self.found_news, [])
        with self._connection() as connection:
            create_schema(connection)

        first = self._initializer(lock=RLock())
        second = self._initializer(lock=RLock())
        load_count = 0
        count_lock = threading.Lock()
        original_load = first._load_json

        def tracked_load(path):
            nonlocal load_count
            with count_lock:
                load_count += 1
            time.sleep(0.05)
            return original_load(path)

        first._load_json = tracked_load
        second._load_json = tracked_load
        start = threading.Barrier(2)

        def initialize(initializer):
            start.wait()
            return initializer.initialize_database()

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(initialize, (first, second)))

        self.assertEqual([item["news_count"] for item in results], [1, 1])
        self.assertEqual(load_count, 2)
        with self._connection() as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM news_items"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM metadata "
                    "WHERE key = 'json_migration_v1'"
                ).fetchone()[0],
                1,
            )


if __name__ == "__main__":
    unittest.main()
