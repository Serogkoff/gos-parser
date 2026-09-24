import sqlite3
import tempfile
import unittest
from pathlib import Path

from utils.storage_schema import create_schema


class StorageSchemaTests(unittest.TestCase):
    def test_schema_creation_is_complete_and_repeatable(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "schema.db"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                create_schema(connection)
                connection.commit()
                create_schema(connection)
                connection.commit()
                tables = {
                    row["name"]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            finally:
                connection.close()

        self.assertTrue({
            "article_cache",
            "bookmarks",
            "calendar_events",
            "dictionary_cards",
            "dictionary_examples",
            "found_item_keywords",
            "news_items",
            "parser_jobs",
            "personal_notes",
            "source_incidents",
            "users",
        }.issubset(tables))

    def test_schema_adds_default_color_to_existing_calendar(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy-calendar.db"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute(
                    """CREATE TABLE calendar_events (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           user_id INTEGER NOT NULL,
                           title TEXT NOT NULL,
                           event_date TEXT NOT NULL,
                           event_time TEXT NOT NULL DEFAULT '',
                           place TEXT NOT NULL DEFAULT '',
                           description TEXT NOT NULL DEFAULT '',
                           visibility TEXT NOT NULL DEFAULT 'private',
                           created_at TEXT NOT NULL,
                           updated_at TEXT NOT NULL
                       )"""
                )
                connection.execute(
                    """INSERT INTO calendar_events(
                           user_id, title, event_date, created_at, updated_at
                       ) VALUES (1, 'Старое событие', '2026-09-14', 'now', 'now')"""
                )
                connection.commit()
                create_schema(connection)
                row = connection.execute(
                    """SELECT title, color, is_bold, is_italic, sort_order
                       FROM calendar_events"""
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(dict(row), {
            "title": "Старое событие",
            "color": "red",
            "is_bold": 0,
            "is_italic": 0,
            "sort_order": 0,
        })

    def test_schema_adds_dictionary_access_to_existing_users(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy-users.db"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute(
                    """CREATE TABLE users (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           username TEXT NOT NULL UNIQUE,
                           password_hash TEXT NOT NULL,
                           role TEXT NOT NULL DEFAULT 'user',
                           is_active INTEGER NOT NULL DEFAULT 1,
                           created_at TEXT NOT NULL,
                           last_login_at TEXT NOT NULL DEFAULT ''
                       )"""
                )
                connection.execute(
                    """INSERT INTO users(username, password_hash, role, created_at)
                       VALUES ('reader', 'hash', 'user', 'now')"""
                )
                connection.commit()
                create_schema(connection)
                row = connection.execute(
                    "SELECT username, can_use_dictionary FROM users"
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(
            dict(row), {"username": "reader", "can_use_dictionary": 0}
        )

    def test_schema_expands_existing_personal_notes_without_data_loss(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy-notes.db"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                connection.execute(
                    """CREATE TABLE personal_notes (
                           id INTEGER PRIMARY KEY AUTOINCREMENT,
                           user_id INTEGER NOT NULL,
                           folder TEXT NOT NULL DEFAULT 'Без папки',
                           title TEXT NOT NULL,
                           body TEXT NOT NULL DEFAULT '',
                           visibility TEXT NOT NULL DEFAULT 'private',
                           created_at TEXT NOT NULL,
                           updated_at TEXT NOT NULL
                       )"""
                )
                connection.execute(
                    """INSERT INTO personal_notes(
                           user_id, title, body, created_at, updated_at
                       ) VALUES (1, 'Старая запись', 'Текст', 'now', 'now')"""
                )
                connection.commit()
                create_schema(connection)
                row = connection.execute(
                    """SELECT title, record_type, tags, is_pinned, is_draft,
                              organization, phone, last_contact_date
                       FROM personal_notes"""
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(dict(row), {
            "title": "Старая запись",
            "record_type": "note",
            "tags": "",
            "is_pinned": 0,
            "is_draft": 0,
            "organization": "",
            "phone": "",
            "last_contact_date": "",
        })

    def test_schema_moves_legacy_dictionary_example_to_separate_rows_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy-dictionary.db"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                create_schema(connection)
                connection.execute(
                    """INSERT INTO users(username, password_hash, role, created_at)
                       VALUES ('owner', 'hash', 'admin', 'now')"""
                )
                connection.execute(
                    """INSERT INTO dictionary_decks(user_id, name, created_at, updated_at)
                       VALUES (1, 'Словарь', 'now', 'now')"""
                )
                connection.execute(
                    """INSERT INTO dictionary_cards(
                           deck_id, user_id, term, translation, example,
                           example_translation, created_at, updated_at
                       ) VALUES (1, 1, '条約', 'договор', '条約を結ぶ。',
                                 'Заключить договор.', 'now', 'now')"""
                )
                connection.commit()
                create_schema(connection)
                connection.commit()
                create_schema(connection)
                rows = connection.execute(
                    """SELECT example_text, translation
                       FROM dictionary_examples WHERE card_id = 1"""
                ).fetchall()
                legacy = connection.execute(
                    """SELECT example, example_translation
                       FROM dictionary_cards WHERE id = 1"""
                ).fetchone()
            finally:
                connection.close()

        self.assertEqual(
            [dict(row) for row in rows],
            [{"example_text": "条約を結ぶ。", "translation": "Заключить договор."}],
        )
        self.assertEqual(dict(legacy), {"example": "", "example_translation": ""})

    def test_schema_normalizes_legacy_publication_dates_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "legacy-dates.db"
            connection = sqlite3.connect(database)
            connection.row_factory = sqlite3.Row
            try:
                create_schema(connection)
                connection.execute(
                    """INSERT INTO news_items(
                           news_key, publication_date, parsed_date,
                           payload_json, updated_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (
                        "legacy",
                        "7 сентября 2026",
                        "2026-09-07 10:15",
                        "{}",
                        "2026-09-07T10:15:00",
                    ),
                )
                connection.execute(
                    "DELETE FROM metadata WHERE key = 'news_publication_dates_v1'"
                )
                connection.commit()

                create_schema(connection)
                normalized = connection.execute(
                    """SELECT publication_date FROM news_items
                       WHERE news_key = 'legacy'"""
                ).fetchone()["publication_date"]
            finally:
                connection.close()

        self.assertEqual(normalized, "2026-09-07")


if __name__ == "__main__":
    unittest.main()
