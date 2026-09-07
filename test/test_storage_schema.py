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
            "found_item_keywords",
            "news_items",
            "parser_jobs",
            "personal_notes",
            "source_incidents",
            "users",
        }.issubset(tables))

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
