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
            "news_items",
            "parser_jobs",
            "personal_notes",
            "source_incidents",
            "users",
        }.issubset(tables))


if __name__ == "__main__":
    unittest.main()
