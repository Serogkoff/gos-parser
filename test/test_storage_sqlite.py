import json
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import web_app
from utils import keywords
from utils import storage


class SQLiteStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.database = directory / "news.db"
        self.backup_directory = directory / "backups"
        self.all_json = directory / "all_news.json"
        self.found_json = directory / "found_news.json"
        self.patchers = (
            patch.object(storage, "DATABASE_FILE", self.database),
            patch.object(storage, "ALL_NEWS_FILE", self.all_json),
            patch.object(storage, "FOUND_NEWS_FILE", self.found_json),
            patch.object(storage, "BACKUP_DIR", self.backup_directory),
        )
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    def _write_json(self, path, value):
        path.write_text(
            json.dumps(value, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_imports_existing_json_once_without_losing_fields(self):
        item = {
            "source": "МЧС",
            "title": "Спасатели провели учения",
            "url": "https://mchs.gov.ru/news/1",
            "date": "2026-08-01",
            "summary": "Официальный анонс публикации.",
        }
        found = {**item, "keywords": ["учения"]}
        self._write_json(self.all_json, [item])
        self._write_json(self.found_json, [found])

        stats = storage.initialize_database()

        self.assertEqual(stats["news_count"], 1)
        self.assertEqual(stats["found_count"], 1)
        self.assertEqual(stats["integrity"], "ok")
        self.assertEqual(storage.load_all_news()[0]["summary"], item["summary"])
        self.assertNotIn("keywords", storage.load_all_news()[0])
        self.assertEqual(storage.load_found_news()[0]["keywords"], ["учения"])

        # Повторная инициализация не импортирует изменённый старый JSON снова.
        self._write_json(self.all_json, [])
        storage.initialize_database()
        self.assertEqual(len(storage.load_all_news()), 1)

    def test_save_updates_existing_item_in_one_database(self):
        old = {
            "source": "Минобороны РФ",
            "title": "Публикация Минобороны",
            "url": "https://z.mil.ru/news/11111111-1111-1111-1111-111111111111",
            "date": "",
        }
        self._write_json(self.all_json, [old])
        self._write_json(self.found_json, [])
        existing_urls = storage.load_existing_urls()
        updated = {
            **old,
            "date": "2026-08-03",
            "summary": "Официальный анонс из карточки публикации.",
        }

        storage.save_results([updated], [], existing_urls)

        saved = storage.load_all_news()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["date"], "2026-08-03")
        self.assertIn("официальный", saved[0]["summary"].casefold())

    def test_replace_found_news_removes_old_matches(self):
        first = {
            "source": "МЧС",
            "title": "Первая новость",
            "url": "https://mchs.gov.ru/news/1",
        }
        second = {
            "source": "МЧС",
            "title": "Вторая новость",
            "url": "https://mchs.gov.ru/news/2",
        }
        self._write_json(self.all_json, [first, second])
        self._write_json(self.found_json, [{**first, "keywords": ["первая"]}])
        storage.initialize_database()

        storage.replace_found_news([{**second, "keywords": ["вторая"]}])

        found = storage.load_found_news()
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["title"], "Вторая новость")

    def test_creates_consistent_backup(self):
        self._write_json(self.all_json, [{
            "source": "РИА Новости",
            "title": "Новость агентства",
            "url": "https://ria.ru/20260803/test.html",
        }])
        self._write_json(self.found_json, [])
        storage.initialize_database()

        backup = storage.backup_database(
            Path(self.temporary.name) / "backups" / "news-copy.db"
        )

        with sqlite3.connect(backup) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM news_items"
            ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_daily_backup_is_created_once_and_old_copies_are_removed(self):
        self._write_json(self.all_json, [{
            "source": "РИА Новости",
            "title": "Новость агентства",
            "url": "https://ria.ru/20260803/daily.html",
        }])
        self._write_json(self.found_json, [])
        storage.initialize_database()

        first = storage.ensure_daily_backup(
            retention=2,
            now=datetime(2026, 8, 1, 10, 0),
        )
        repeated = storage.ensure_daily_backup(
            retention=2,
            now=datetime(2026, 8, 1, 20, 0),
        )
        storage.ensure_daily_backup(
            retention=2,
            now=datetime(2026, 8, 2, 10, 0),
        )
        latest = storage.ensure_daily_backup(
            retention=2,
            now=datetime(2026, 8, 3, 10, 0),
        )

        self.assertTrue(first["created"])
        self.assertFalse(repeated["created"])
        self.assertEqual(len(list(self.backup_directory.glob("*.db"))), 2)
        self.assertFalse(
            (self.backup_directory / "news-2026-08-01.db").exists()
        )
        self.assertEqual(len(latest["removed"]), 1)

    def test_prepare_database_reports_operational_status(self):
        self._write_json(self.all_json, [])
        self._write_json(self.found_json, [])

        stats = storage.prepare_database(retention=7)

        self.assertEqual(stats["integrity"], "ok")
        self.assertEqual(stats["journal_mode"].casefold(), "wal")
        self.assertTrue(stats["json_migrated"])
        self.assertTrue(stats["backup_created"])
        self.assertEqual(stats["backup_count"], 1)

    def test_web_interface_reads_news_from_sqlite(self):
        item = {
            "source": "МЧС",
            "title": "Материал из базы SQLite",
            "url": "https://mchs.gov.ru/news/sqlite-test",
            "date": "2026-08-03",
        }
        self._write_json(self.all_json, [item])
        self._write_json(self.found_json, [])
        storage.initialize_database()

        loaded = web_app.load_json("all_news.json", [])

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["title"], item["title"])

    def test_keyword_rebuild_writes_matches_to_sqlite(self):
        item = {
            "source": "МИД РФ",
            "title": "Заявление о Курильских островах",
            "url": "https://mid.ru/news/sqlite-test",
            "date": "2026-08-03",
        }
        self._write_json(self.all_json, [item])
        self._write_json(self.found_json, [])
        storage.initialize_database()

        with patch.object(keywords, "load_keywords", return_value=["Курил"]):
            rebuilt = keywords.rebuild_found_news()

        self.assertEqual(len(rebuilt), 1)
        self.assertEqual(storage.load_found_news()[0]["keywords"], ["Курил"])


if __name__ == "__main__":
    unittest.main()
