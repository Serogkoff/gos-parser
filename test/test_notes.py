import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import web_app
from utils import storage


class NotesTestModeTests(unittest.TestCase):
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
        self.admin = storage.create_user("owner", "owner-secret-2026", role="admin")
        self.reader = storage.create_user("reader", "reader-secret-2026", role="user")

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled
        web_app.app.config["TESTING"] = False
        for patcher in reversed(self.patchers):
            patcher.stop()
        gc.collect()
        self.temporary.cleanup()

    @staticmethod
    def _client_for(user, token="notes-test-csrf"):
        client = web_app.app.test_client()
        with client.session_transaction() as session:
            session["user_id"] = user["id"]
            session["_csrf_token"] = token
        return client, token

    @staticmethod
    def _empty_app_data(filename, default):
        if filename == "parser_status.json":
            return {"sources": [], "generated_at": ""}
        return []

    def test_section_is_hidden_and_forbidden_for_regular_user(self):
        client, _ = self._client_for(self.reader)

        self.assertEqual(client.get("/notes").status_code, 403)
        with patch.object(web_app, "load_json", side_effect=self._empty_app_data):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('href="/notes"', page.get_data(as_text=True))

        admin_client, _ = self._client_for(self.admin)
        with patch.object(web_app, "load_json", side_effect=self._empty_app_data):
            admin_page = admin_client.get("/")
        self.assertIn('href="/notes"', admin_page.get_data(as_text=True))

    def test_admin_creates_event_and_opens_selected_day(self):
        client, token = self._client_for(self.admin)
        response = client.post(
            "/notes?view=calendar",
            data={
                "csrf_token": token,
                "action": "save_event",
                "title": "Встреча в МИД",
                "event_date": "2026-08-28",
                "event_time": "14:00",
                "place": "Смоленская площадь",
                "description": "Взять паспорт",
                "visibility": "selected",
                "shared_user_ids": [str(self.reader["id"])],
            },
        )

        self.assertEqual(response.status_code, 302)
        events = storage.list_calendar_events(
            self.admin["id"], "2026-08-01", "2026-08-31"
        )
        self.assertEqual(events[0]["title"], "Встреча в МИД")
        self.assertEqual(events[0]["shared_users"][0]["username"], "reader")
        page = client.get("/notes?view=calendar&year=2026&month=8&selected=2026-08-28")
        html = page.get_data(as_text=True)
        self.assertIn("28.08.2026", html)
        self.assertIn("Встреча в МИД", html)
        self.assertIn("Смоленская площадь", html)

    def test_admin_uses_records_and_dictionary_quiz(self):
        client, token = self._client_for(self.admin)
        note = client.post(
            "/notes?view=records",
            data={
                "csrf_token": token,
                "action": "save_note",
                "folder": "Контакты",
                "title": "Пресс-центр",
                "body": "+7 495 000-00-00",
                "visibility": "private",
            },
        )
        self.assertEqual(note.status_code, 302)
        self.assertIn("Пресс-центр", client.get("/notes?view=records").get_data(as_text=True))

        deck = client.post(
            "/notes?view=dictionary",
            data={"csrf_token": token, "action": "create_deck", "name": "Политика"},
        )
        self.assertEqual(deck.status_code, 302)
        deck_id = storage.list_dictionary_decks(self.admin["id"])[0]["id"]
        card = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "add_card",
                "deck_id": deck_id,
                "term": "記者会見",
                "reading": "きしゃかいけん",
                "translation": "пресс-конференция",
            },
        )
        self.assertEqual(card.status_code, 302)
        page = client.get(f"/notes?view=dictionary&deck={deck_id}")
        self.assertIn("記者会見", page.get_data(as_text=True))
        card_id = storage.list_dictionary_cards(self.admin["id"], deck_id)[0]["id"]
        review = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "review_card",
                "deck_id": deck_id,
                "card_id": card_id,
                "rating": "good",
            },
        )
        self.assertEqual(review.status_code, 302)
        reviewed = storage.list_dictionary_cards(self.admin["id"], deck_id)[0]
        self.assertEqual(reviewed["interval_days"], 1)
        self.assertTrue(reviewed["next_review"])


if __name__ == "__main__":
    unittest.main()
