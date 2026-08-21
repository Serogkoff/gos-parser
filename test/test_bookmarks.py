import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_app
from utils import storage


class PersonalBookmarksTests(unittest.TestCase):
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
        self.first = storage.create_user("first", "first-secret-2026")
        self.second = storage.create_user("second", "second-secret-2026")
        self.item = {
            "source": "Коммерсантъ",
            "title": "Материал для личных закладок",
            "url": "https://www.kommersant.ru/doc/999001",
            "date": "2026-08-12",
        }
        storage.save_results([self.item], [], set())

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled
        web_app.app.config["TESTING"] = False
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    @staticmethod
    def _login(client, user_id, token="test-csrf-token"):
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["_csrf_token"] = token
        return token

    def test_folders_notes_and_bookmarks_are_isolated_by_user(self):
        first_folder = storage.create_bookmark_folder(self.first["id"], "Выборы")
        second_folder = storage.create_bookmark_folder(self.second["id"], "Япония")
        storage.save_bookmark(
            self.first["id"],
            self.item,
            first_folder["id"],
            "Проверить фамилии участников.",
        )

        self.assertEqual(len(storage.list_bookmarks(self.first["id"])), 1)
        self.assertEqual(storage.list_bookmarks(self.second["id"]), [])
        self.assertEqual(
            storage.list_bookmarks(self.first["id"])[0]["note"],
            "Проверить фамилии участников.",
        )
        with self.assertRaisesRegex(ValueError, "Папка не найдена"):
            storage.update_bookmark(
                self.first["id"],
                self.item["url"],
                second_folder["id"],
                "Чужая папка",
            )

    def test_deleting_folder_keeps_bookmark_unfiled(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Санкции")
        storage.save_bookmark(self.first["id"], self.item, folder["id"])

        storage.delete_bookmark_folder(self.first["id"], folder["id"])

        bookmark = storage.list_bookmarks(self.first["id"])[0]
        self.assertIsNone(bookmark["folder_id"])
        self.assertEqual(storage.list_bookmarks(self.first["id"], "unfiled"), [bookmark])

    def test_feed_api_and_bookmarks_page_use_current_account(self):
        first_client = web_app.app.test_client()
        token = self._login(first_client, self.first["id"])
        saved = first_client.post(
            "/api/bookmarks",
            json={"url": self.item["url"]},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.get_json()["count"], 1)
        page = first_client.get("/bookmarks")
        self.assertIn(self.item["title"], page.get_data(as_text=True))

        second_client = web_app.app.test_client()
        self._login(second_client, self.second["id"])
        self.assertEqual(second_client.get("/api/bookmarks").get_json()["count"], 0)
        self.assertNotIn(
            self.item["title"],
            second_client.get("/bookmarks").get_data(as_text=True),
        )

    def test_bookmark_mutation_requires_csrf_token(self):
        client = web_app.app.test_client()
        self._login(client, self.first["id"])
        response = client.post(
            "/api/bookmarks",
            json={"url": self.item["url"]},
            headers={"X-CSRF-Token": "wrong-token"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(storage.count_bookmarks(self.first["id"]), 0)

    def test_legacy_browser_bookmarks_are_imported_in_one_request(self):
        client = web_app.app.test_client()
        token = self._login(client, self.first["id"])

        response = client.post(
            "/api/bookmarks",
            json={
                "urls": [
                    self.item["url"],
                    "https://example.invalid/news-not-in-database",
                ]
            },
            headers={"X-CSRF-Token": token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["count"], 1)
        self.assertEqual(storage.count_bookmarks(self.first["id"]), 1)

    def test_collection_access_is_inherited_and_read_only(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Выборы")
        storage.save_bookmark(self.first["id"], self.item, folder["id"])
        storage.save_collection_note(
            self.first["id"], folder["id"], "Справка", "Следить за обновлениями."
        )
        storage.update_collection(
            self.first["id"], folder["id"], "Выборы", "Материалы для шефа",
            "selected", [self.second["id"]],
        )

        shared = storage.load_collection(self.second["id"], folder["id"])
        self.assertFalse(shared["can_edit"])
        self.assertEqual(shared["owner_name"], "first")
        self.assertEqual(
            storage.list_collection_bookmarks(self.second["id"], folder["id"])[0]["title"],
            self.item["title"],
        )
        self.assertEqual(
            storage.list_collection_notes(self.second["id"], folder["id"])[0]["title"],
            "Справка",
        )
        with self.assertRaisesRegex(ValueError, "Папка не найдена"):
            storage.save_collection_note(
                self.second["id"], folder["id"], "Чужая правка", "Нельзя"
            )

    def test_private_collection_is_not_visible_to_another_user(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Закрыто")

        self.assertIsNone(storage.load_collection(self.second["id"], folder["id"]))
        self.assertEqual(storage.list_shared_collections(self.second["id"]), [])

    def test_external_link_and_note_are_added_to_collection(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Внешние материалы")
        storage.save_external_bookmark(
            self.first["id"], folder["id"], "https://example.com/report",
            "Доклад наблюдателей", "Проверить выводы",
        )
        note_id = storage.save_collection_note(
            self.first["id"], folder["id"], "План", "Сопоставить с официальными данными."
        )

        item = storage.list_collection_bookmarks(self.first["id"], folder["id"])[0]
        self.assertEqual(item["source"], "Внешний источник")
        self.assertEqual(item["note"], "Проверить выводы")
        storage.delete_collection_note(self.first["id"], folder["id"], note_id)
        self.assertEqual(storage.list_collection_notes(self.first["id"], folder["id"]), [])


if __name__ == "__main__":
    unittest.main()
