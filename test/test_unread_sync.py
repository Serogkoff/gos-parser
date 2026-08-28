import gc
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_app
from utils import storage


class UnreadSyncTests(unittest.TestCase):
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
        self.previous_auth_disabled = web_app.app.config["AUTH_DISABLED"]
        web_app.app.config["AUTH_DISABLED"] = False
        web_app.app.config["TESTING"] = True
        self.owner = storage.create_user("owner", "owner-secret-2026", role="admin")
        self.reader = storage.create_user("reader", "reader-secret-2026")
        self._insert_news(
            {
                "source": "МЧС",
                "title": "Старая публикация",
                "url": "https://mchs.gov.ru/news/old",
                "date": "2026-08-27",
            }
        )

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled
        web_app.app.config["TESTING"] = False
        for patcher in reversed(self.patchers):
            patcher.stop()
        gc.collect()
        self.temporary.cleanup()

    @staticmethod
    def _client_for(user, token="unread-test-csrf"):
        client = web_app.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user["id"]
            session["_csrf_token"] = token
        return client, token

    @staticmethod
    def _unread(client, group):
        response = client.get(f"/api/news-index?group={group}")
        return response, response.get_json()["unread_urls"]

    @staticmethod
    def _insert_news(*items):
        storage.initialize_database()
        with storage._connection() as connection:
            storage._insert_news_items(connection, items)

    def test_read_mark_is_shared_between_devices_but_not_users(self):
        first_device, token = self._client_for(self.owner)
        second_device, _ = self._client_for(self.owner, token="second-device")
        other_user, _ = self._client_for(self.reader, token="reader-token")

        # Первый запрос создаёт личную границу и не помечает архив новым.
        self.assertEqual(self._unread(first_device, "government")[1], [])
        self.assertEqual(self._unread(other_user, "government")[1], [])

        fresh_url = "https://mchs.gov.ru/news/fresh"
        self._insert_news(
            {
                "source": "МЧС",
                "title": "Свежая публикация",
                "url": fresh_url,
                "date": "2026-08-28",
            }
        )
        self.assertEqual(self._unread(first_device, "government")[1], [fresh_url])
        self.assertEqual(self._unread(other_user, "government")[1], [fresh_url])

        marked = first_device.post(
            "/api/news-read",
            json={"url": fresh_url},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(self._unread(second_device, "government")[1], [])
        self.assertEqual(self._unread(other_user, "government")[1], [fresh_url])

    def test_read_all_affects_only_selected_source_group(self):
        client, token = self._client_for(self.owner)
        self.assertEqual(self._unread(client, "government")[1], [])
        self.assertEqual(self._unread(client, "agencies")[1], [])

        government_url = "https://mchs.gov.ru/news/government-new"
        agency_url = "https://tass.ru/politika/agency-new"
        self._insert_news(
            {
                "source": "МЧС",
                "title": "Новая публикация ведомства",
                "url": government_url,
                "date": "2026-08-28",
            },
            {
                "source": "ТАСС",
                "title": "Новая публикация агентства",
                "url": agency_url,
                "date": "2026-08-28",
            },
        )
        response = client.post(
            "/api/news-read",
            json={"all": True, "source_group": "government"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._unread(client, "government")[1], [])
        self.assertEqual(self._unread(client, "agencies")[1], [agency_url])

    def test_state_change_requires_csrf_token(self):
        client, _ = self._client_for(self.owner)
        response = client.post(
            "/api/news-read",
            json={"all": True, "source_group": "government"},
        )
        self.assertEqual(response.status_code, 400)

    def test_legacy_browser_unread_is_migrated_only_once(self):
        first_device, token = self._client_for(self.owner)
        second_device, _ = self._client_for(self.owner, token="second-device")
        old_url = "https://mchs.gov.ru/news/old"

        migrated = first_device.post(
            "/api/news-read/migrate",
            json={"unread_urls": [old_url]},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(migrated.status_code, 200)
        self.assertTrue(migrated.get_json()["migrated"])
        self.assertEqual(self._unread(second_device, "government")[1], [old_url])

        ignored = second_device.post(
            "/api/news-read/migrate",
            json={"unread_urls": []},
            headers={"X-CSRF-Token": "second-device"},
        )
        self.assertEqual(ignored.status_code, 200)
        self.assertFalse(ignored.get_json()["migrated"])
        self.assertEqual(self._unread(first_device, "government")[1], [old_url])

    def test_parser_refresh_preserves_first_seen_and_read_marks(self):
        client, token = self._client_for(self.owner)
        self.assertEqual(self._unread(client, "government")[1], [])

        fresh_url = "https://mchs.gov.ru/news/preserved"
        existing_urls = storage.load_existing_urls()
        fresh_item = {
            "source": "МЧС",
            "title": "Публикация после обновления парсера",
            "url": fresh_url,
            "date": "2026-08-28",
        }
        storage.save_results([fresh_item], [], existing_urls)
        self.assertEqual(self._unread(client, "government")[1], [fresh_url])

        marked = client.post(
            "/api/news-read",
            json={"url": fresh_url},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(marked.status_code, 200)

        storage.save_results(
            [fresh_item], [], storage.load_existing_urls(),
        )
        self.assertEqual(self._unread(client, "government")[1], [])

    def test_existing_database_gains_first_seen_without_losing_news(self):
        legacy_database = Path(self.temporary.name) / "legacy-news.db"
        with sqlite3.connect(legacy_database) as connection:
            connection.execute(
                """CREATE TABLE news_items (
                    news_key TEXT PRIMARY KEY,
                    normalized_url TEXT NOT NULL DEFAULT '',
                    source TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    publication_date TEXT NOT NULL DEFAULT '',
                    parsed_date TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            connection.execute(
                """INSERT INTO news_items VALUES (
                    'url:https://example.ru/old', 'https://example.ru/old',
                    'МЧС', 'Архив', '2026-08-20', '', '{}',
                    '2026-08-20T10:00:00'
                )"""
            )

        with patch.object(storage, "DATABASE_FILE", legacy_database):
            storage.initialize_database()
            with storage._connection() as connection:
                columns = {
                    row["name"]
                    for row in connection.execute(
                        "PRAGMA table_info(news_items)"
                    ).fetchall()
                }
                row = connection.execute(
                    "SELECT first_seen_at FROM news_items"
                ).fetchone()

        self.assertIn("first_seen_at", columns)
        self.assertEqual(row["first_seen_at"], "2026-08-20T10:00:00")


if __name__ == "__main__":
    unittest.main()
