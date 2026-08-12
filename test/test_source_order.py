import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_app
from utils import storage
from utils.source_groups import GOVERNMENT_GROUP


class PersonalSourceOrderTests(unittest.TestCase):
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
        self.news = [
            {
                "source": "МЧС",
                "title": "Материал МЧС",
                "url": "https://mchs.gov.ru/news/1",
                "date": "2026-08-12",
            },
            {
                "source": "Правительство РФ",
                "title": "Материал Правительства",
                "url": "http://government.ru/news/1/",
                "date": "2026-08-12",
            },
            {
                "source": "МВД РФ",
                "title": "Материал МВД",
                "url": "https://mvd.ru/news/item/1/",
                "date": "2026-08-12",
            },
        ]
        storage.save_results(self.news, [], set())

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled
        web_app.app.config["TESTING"] = False
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    @staticmethod
    def _login(client, user_id, token="source-order-csrf"):
        with client.session_transaction() as session:
            session["user_id"] = user_id
            session["_csrf_token"] = token
        return token

    @staticmethod
    def _app_data(filename, default):
        if filename == "all_news.json":
            return storage.load_all_news()
        if filename == "found_news.json":
            return []
        if filename == "parser_status.json":
            return {
                "generated_at": "2026-08-12 16:00:00",
                "sources": [
                    {"source": "МЧС", "status": "ok"},
                    {"source": "Правительство РФ", "status": "ok"},
                    {"source": "МВД РФ", "status": "ok"},
                ],
            }
        return default

    def test_saved_order_is_isolated_by_user_and_group(self):
        storage.save_source_order(
            self.first["id"],
            GOVERNMENT_GROUP,
            ["МЧС", "МВД РФ", "Правительство РФ"],
        )

        self.assertEqual(
            storage.load_source_order(self.first["id"], GOVERNMENT_GROUP),
            ["МЧС", "МВД РФ", "Правительство РФ"],
        )
        self.assertEqual(
            storage.load_source_order(self.second["id"], GOVERNMENT_GROUP),
            [],
        )

    def test_api_saves_and_page_uses_personal_order(self):
        client = web_app.app.test_client()
        token = self._login(client, self.first["id"])
        with patch.object(web_app, "load_json", side_effect=self._app_data):
            response = client.post(
                "/api/source-order",
                json={
                    "source_group": GOVERNMENT_GROUP,
                    "sources": ["Правительство РФ", "МЧС", "МВД РФ"],
                },
                headers={"X-CSRF-Token": token},
            )
            page = client.get("/")

        self.assertEqual(response.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertLess(
            html.index('data-source-name="Правительство РФ"'),
            html.index('data-source-name="МЧС"'),
        )
        self.assertIn("data-source-up", html)
        self.assertIn("data-source-down", html)

    def test_header_is_compact_and_filters_button_is_removed(self):
        client = web_app.app.test_client()
        self._login(client, self.first["id"])
        with patch.object(web_app, "load_json", side_effect=self._app_data):
            html = client.get("/").get_data(as_text=True)

        header = html[html.index('<header class="topbar">'):html.index("</header>")]
        self.assertNotIn("Госструктуры <span>", header)
        self.assertNotIn("Информагентства <span>", header)
        self.assertNotIn("Газеты <span>", header)
        self.assertNotIn('id="toggle-sidebar"', html)
        self.assertNotIn("☷ Фильтры", html)
        self.assertIn('class="account-status"', header)
        self.assertGreater(header.index('class="health '), header.index('class="account"'))

    def test_source_order_api_requires_csrf(self):
        client = web_app.app.test_client()
        self._login(client, self.first["id"])
        response = client.post(
            "/api/source-order",
            json={
                "source_group": GOVERNMENT_GROUP,
                "sources": ["МЧС"],
            },
            headers={"X-CSRF-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            storage.load_source_order(self.first["id"], GOVERNMENT_GROUP),
            [],
        )


if __name__ == "__main__":
    unittest.main()
