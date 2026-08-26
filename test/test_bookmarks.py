import io
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

import web_app
from docx import Document
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
        favorite = next(
            folder for folder in storage.list_bookmark_folders(self.first["id"])
            if folder["system_key"] == "favorites"
        )
        saved_item = storage.list_bookmarks(self.first["id"])[0]
        self.assertEqual(saved_item["folder_id"], favorite["id"])
        self.assertEqual(favorite["name"], "Моё избранное")
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
        note_id = storage.list_collection_notes(
            self.second["id"], folder["id"],
        )[0]["id"]
        with self.assertRaisesRegex(ValueError, "Папка не найдена"):
            storage.update_collection_note(
                self.second["id"], folder["id"], note_id,
                "Чужая правка", "Нельзя",
            )

    def test_private_collection_is_not_visible_to_another_user(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Закрыто")

        self.assertIsNone(storage.load_collection(self.second["id"], folder["id"]))
        self.assertEqual(storage.list_shared_collections(self.second["id"]), [])

    def test_article_read_mark_is_personal_and_available_to_shared_reader(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Общая папка")
        note_id = storage.save_collection_note(
            self.first["id"], folder["id"], "Статья для чтения", "Текст статьи"
        )
        storage.update_collection(
            self.first["id"], folder["id"], "Общая папка", "", "selected",
            [self.second["id"]],
        )
        owner_client = web_app.app.test_client()
        owner_token = self._login(owner_client, self.first["id"], "owner-csrf")
        reader_client = web_app.app.test_client()
        self._login(reader_client, self.second["id"], "reader-csrf")

        owner_page = owner_client.get(
            f"/collections?folder={folder['id']}"
        ).get_data(as_text=True)
        self.assertIn('data-article-read', owner_page)
        self.assertIn('aria-pressed="false"', owner_page)
        response = owner_client.post(
            "/api/collection-note-read",
            json={"folder_id": folder["id"], "note_id": note_id, "is_read": True},
            headers={"X-CSRF-Token": owner_token},
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["is_read"])
        self.assertEqual(
            storage.list_collection_note_read_ids(self.first["id"], folder["id"]),
            {note_id},
        )
        self.assertEqual(
            storage.list_collection_note_read_ids(self.second["id"], folder["id"]),
            set(),
        )
        reader_page = reader_client.get(
            f"/collections?folder={folder['id']}"
        ).get_data(as_text=True)
        self.assertIn('aria-pressed="false"', reader_page)
        self.assertIn("article-read-toggle::before", reader_page)
        owner_page = owner_client.get(
            f"/collections?folder={folder['id']}"
        ).get_data(as_text=True)
        self.assertIn('aria-pressed="true"', owner_page)
        self.assertIn('article-read-toggle[aria-pressed="true"]::before', owner_page)
        response = owner_client.post(
            "/api/collection-note-read",
            json={"folder_id": folder["id"], "note_id": note_id, "is_read": False},
            headers={"X-CSRF-Token": owner_token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["is_read"])
        self.assertEqual(
            storage.list_collection_note_read_ids(self.first["id"], folder["id"]),
            set(),
        )

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

    def test_unified_note_form_stores_article_fields_and_compacts_long_text(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Топливный кризис")
        client = web_app.app.test_client()
        token = self._login(client, self.first["id"])
        body = "\n\n".join(
            f"Абзац {number}: подробности материала о поставках топлива."
            for number in range(1, 6)
        )

        response = client.post(
            f"/collections?folder={folder['id']}",
            data={
                "csrf_token": token,
                "action": "add_note",
                "folder_id": folder["id"],
                "url": "https://example.com/fuel-report",
                "source": "Коммерсантъ",
                "publication_date": "2026-08-21",
                "title": "На АЗС рассказали о лимитах",
                "body": body,
                "comment": "Проверить данные Минэнерго",
            },
        )

        self.assertEqual(response.status_code, 302)
        note = storage.list_collection_notes(self.first["id"], folder["id"])[0]
        self.assertEqual(note["source"], "Коммерсантъ")
        self.assertEqual(note["publication_date"], "2026-08-21")
        self.assertEqual(note["url"], "https://example.com/fuel-report")
        prepared = web_app._prepare_collection_note(note)
        self.assertIn("Абзац 1", prepared["body_preview"])
        self.assertNotIn("Абзац 2", prepared["body_preview"])
        self.assertIn("Абзац 2", prepared["body_remainder"])
        page = client.get(f"/collections?folder={folder['id']}").get_data(as_text=True)
        self.assertIn("Читать полностью", page)
        self.assertIn("data-note-toggle", page)
        self.assertIn("Свернуть", page)
        self.assertNotIn("<details", page)
        self.assertIn("Оригинал ↗", page)
        self.assertIn("Коммерсантъ", page)
        self.assertIn("2026-08-21", page)
        self.assertNotIn(note["updated_at"], page)
        self.assertNotIn("Добавить ссылку", page)
        self.assertNotIn("Добавить заметку", page)
        self.assertIn("+ Добавить статью", page)
        self.assertIn("Новая статья", page)
        self.assertIn("Сохранить в подборку", page)
        self.assertIn("data-composer-form method=\"post\" hidden", page)
        self.assertIn("<span class=\"badge\">Статья</span>", page)
        title_position = page.index(note["title"])
        source_position = page.index("material-footer", title_position)
        body_position = page.index("Абзац 1", title_position)
        self.assertLess(title_position, source_position)
        self.assertLess(source_position, body_position)

        found = client.get(
            f"/collections?folder={folder['id']}&q=Минэнерго"
        ).get_data(as_text=True)
        missing = client.get(
            f"/collections?folder={folder['id']}&q=авиаперевозки"
        ).get_data(as_text=True)
        self.assertIn(note["title"], found)
        self.assertNotIn(note["title"], missing)
        self.assertIn("Ничего не найдено", missing)

        response = client.post(
            f"/collections?folder={folder['id']}",
            data={
                "csrf_token": token,
                "action": "update_note",
                "folder_id": folder["id"],
                "note_id": note["id"],
                "url": "https://example.com/updated-report",
                "source": "Forbes",
                "publication_date": "2026-08-20",
                "title": "Обновлённый заголовок",
                "body": "Новый первый абзац.\n\nНовый второй абзац.",
                "comment": "Комментарий обновлён",
            },
        )
        self.assertEqual(response.status_code, 302)
        updated_notes = storage.list_collection_notes(
            self.first["id"], folder["id"],
        )
        self.assertEqual(len(updated_notes), 1)
        self.assertEqual(updated_notes[0]["id"], note["id"])
        self.assertEqual(updated_notes[0]["title"], "Обновлённый заголовок")
        self.assertEqual(updated_notes[0]["source"], "Forbes")
        self.assertEqual(updated_notes[0]["publication_date"], "2026-08-20")
        self.assertEqual(updated_notes[0]["comment"], "Комментарий обновлён")
        updated_page = client.get(
            f"/collections?folder={folder['id']}"
        ).get_data(as_text=True)
        self.assertIn("Сохранить изменения", updated_page)
        self.assertIn("data-note-edit-toggle", updated_page)

    def test_user_can_change_collection_order(self):
        first = storage.create_bookmark_folder(self.first["id"], "Первая")
        second = storage.create_bookmark_folder(self.first["id"], "Вторая")
        third = storage.create_bookmark_folder(self.first["id"], "Третья")

        self.assertEqual(
            [item["id"] for item in storage.list_bookmark_folders(self.first["id"])],
            [first["id"], second["id"], third["id"]],
        )
        storage.save_bookmark_folder_order(
            self.first["id"],
            [third["id"], first["id"], second["id"]],
        )

        self.assertEqual(
            [item["id"] for item in storage.list_bookmark_folders(self.first["id"])],
            [third["id"], first["id"], second["id"]],
        )
        client = web_app.app.test_client()
        token = self._login(client, self.first["id"])
        response = client.post(
            "/api/collection-order",
            json={"folder_ids": [second["id"], third["id"], first["id"]]},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            [item["id"] for item in storage.list_bookmark_folders(self.first["id"])],
            [second["id"], third["id"], first["id"]],
        )
        page = client.get("/collections").get_data(as_text=True)
        self.assertIn("folder-order-toggle", page)
        self.assertIn("data-folder-row", page)
        self.assertNotIn("Поднять подборку", page)

    def test_collection_sidebar_scrolls_independently_and_toolbar_has_no_button(self):
        client = web_app.app.test_client()
        self._login(client, self.first["id"])

        page = client.get("/").get_data(as_text=True)
        collections = client.get("/collections").get_data(as_text=True)

        self.assertNotIn('class="toolbar-link" href="/collections"', page)
        self.assertIn("height:calc(100vh - 36px)", collections)
        self.assertIn("overflow-y:auto", collections)
        self.assertIn("overscroll-behavior:contain", collections)

    def test_collection_can_be_sorted_and_exported_to_word(self):
        folder = storage.create_bookmark_folder(self.first["id"], "Доклад шефу")
        older = dict(
            self.item,
            title="Аналитика за понедельник",
            url="https://www.kommersant.ru/doc/999002",
            date="2026-08-20",
        )
        newer = dict(
            self.item,
            title="Сводка за вторник",
            url="https://www.kommersant.ru/doc/999003",
            date="2026-08-26",
        )
        storage.save_bookmark(self.first["id"], older, folder["id"])
        storage.save_bookmark(self.first["id"], newer, folder["id"])
        client = web_app.app.test_client()
        self._login(client, self.first["id"])

        sorted_page = client.get(
            f"/collections?folder={folder['id']}&sort=oldest"
        ).get_data(as_text=True)
        self.assertLess(
            sorted_page.index(older["title"]),
            sorted_page.index(newer["title"]),
        )
        self.assertIn("Сначала старые", sorted_page)

        response = client.get(
            f"/collections/export.docx?folder={folder['id']}&sort=oldest"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "application/vnd.openxmlformats-officedocument",
            response.content_type,
        )
        document = Document(io.BytesIO(response.data))
        text = "\n".join(paragraph.text for paragraph in document.paragraphs)
        self.assertIn("Доклад шефу", text)
        self.assertIn(older["title"], text)
        self.assertIn("Источник: Коммерсантъ", text)
        self.assertIn("Дата публикации: 2026-08-20", text)
        self.assertIn(older["url"], text)

    def test_collection_schema_migrates_without_losing_existing_notes(self):
        legacy_database = Path(self.temporary.name) / "legacy-collections.db"
        # sqlite3.Connection как context manager фиксирует транзакцию, но сам
        # дескриптор не закрывает. На Windows это блокирует TemporaryDirectory.
        with closing(sqlite3.connect(legacy_database)) as connection:
            connection.executescript(
                """
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_login_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE bookmark_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    name TEXT NOT NULL COLLATE NOCASE,
                    description TEXT NOT NULL DEFAULT '',
                    visibility TEXT NOT NULL DEFAULT 'private',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT '',
                    UNIQUE(user_id, name)
                );
                CREATE TABLE collection_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    folder_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO users(
                    id, username, password_hash, role, is_active, created_at
                ) VALUES (1, 'legacy', 'hash', 'user', 1, '2026-08-20');
                INSERT INTO bookmark_folders(
                    id, user_id, name, created_at, updated_at
                ) VALUES (1, 1, 'Старая подборка', '2026-08-20', '2026-08-20');
                INSERT INTO collection_notes(
                    id, folder_id, user_id, title, body, created_at, updated_at
                ) VALUES (
                    1, 1, 1, 'Старая заметка', 'Текст сохранён',
                    '2026-08-20', '2026-08-20'
                );
                """
            )

        with patch.object(storage, "DATABASE_FILE", legacy_database):
            storage.initialize_database()
            notes = storage.list_collection_notes(1, 1)
            folders = storage.list_bookmark_folders(1)

        self.assertEqual(notes[0]["title"], "Старая заметка")
        self.assertEqual(notes[0]["body"], "Текст сохранён")
        self.assertEqual(notes[0]["source"], "")
        self.assertEqual(folders[0]["sort_order"], 0)
        self.assertEqual(folders[0]["system_key"], "")


if __name__ == "__main__":
    unittest.main()
