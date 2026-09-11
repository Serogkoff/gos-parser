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

    def test_parser_update_does_not_delete_the_news_table(self):
        first = self._item(1, summary="Старая версия")
        untouched = self._item(2, summary="Не менялась")
        storage.save_results([first, untouched], [], set())
        persistence = storage._NEWS_PERSISTENCE
        with (
            patch.object(
                persistence,
                "replace_collections",
                side_effect=AssertionError("full replacement is forbidden"),
            ),
            patch.object(
                persistence,
                "upsert_news_items",
                wraps=persistence.upsert_news_items,
            ) as upsert,
        ):
            storage.save_results(
                [{**first, "summary": "Новая версия"}],
                [],
                storage.load_existing_urls(),
            )

        self.assertEqual(len(upsert.call_args.args[1]), 1)
        self.assertEqual(upsert.call_args.args[1][0]["url"], first["url"])
        self.assertEqual(len(storage.load_all_news()), 2)

    def test_parser_cycle_does_not_load_the_complete_news_collections(self):
        first = self._item(1)
        storage.save_results([first], [], set())

        with (
            patch.object(
                storage._NEWS_PERSISTENCE,
                "_load_all_news",
                side_effect=AssertionError("complete news load is forbidden"),
            ),
            patch.object(
                storage._NEWS_PERSISTENCE,
                "_load_found_news",
                side_effect=AssertionError("complete matches load is forbidden"),
            ),
        ):
            storage.save_results(
                [{**first, "summary": "Уточнённый анонс"}],
                [],
                storage.load_existing_urls(),
            )

        self.assertEqual(storage.load_all_news()[0]["summary"], "Уточнённый анонс")

    def test_limited_cycle_keeps_title_based_deduplication(self):
        original = {
            "source": "МЧС",
            "title": "Спасатели провели учения",
            "url": "https://mchs.gov.ru/news/old-address",
            "date": "2026-09-01",
        }
        storage.save_results([original], [], set())
        corrected = {
            **original,
            "url": "https://mchs.gov.ru/news/correct-address",
            "summary": "Адрес публикации исправлен.",
        }

        storage.save_results(
            [corrected], [], storage.load_existing_urls(),
        )

        saved = storage.load_all_news()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["url"], corrected["url"])
        self.assertEqual(saved[0]["summary"], corrected["summary"])

    def test_limited_cycle_keeps_ministry_of_defense_uuid_deduplication(self):
        article_id = "11111111-1111-1111-1111-111111111111"
        original = self._item(
            1,
            source="Минобороны РФ",
            url=f"https://z.mil.ru/news/{article_id}",
        )
        storage.save_results([original], [], set())
        corrected = {
            **original,
            "url": f"https://mil.ru/news/{article_id}",
            "summary": "Основной домен восстановлен.",
        }

        storage.save_results(
            [corrected], [], storage.load_existing_urls(),
        )

        saved = storage.load_all_news()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]["url"], corrected["url"])

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
