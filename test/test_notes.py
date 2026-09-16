import gc
import tempfile
import unittest
from datetime import date, timedelta
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
                "color": "green",
                "is_bold": "1",
                "is_italic": "1",
                "calendar_mode": "month",
            },
        )

        self.assertEqual(response.status_code, 302)
        events = storage.list_calendar_events(
            self.admin["id"], "2026-08-01", "2026-08-31"
        )
        self.assertEqual(events[0]["title"], "Встреча в МИД")
        self.assertEqual(events[0]["visibility"], "private")
        self.assertEqual(events[0]["color"], "green")
        self.assertEqual(events[0]["is_bold"], 1)
        self.assertEqual(events[0]["is_italic"], 1)
        self.assertEqual(events[0]["shared_users"], [])
        page = client.get("/notes?view=calendar&year=2026&month=8&selected=2026-08-28")
        html = page.get_data(as_text=True)
        self.assertIn("Август 2026", html)
        self.assertIn("Встреча в МИД", html)
        self.assertIn("Календарь", html)
        self.assertIn("Записи", html)
        self.assertIn("Словарь-квиз", html)
        self.assertNotIn("Выбранные пользователи", html)
        self.assertIn("event-bold", html)
        self.assertIn("event-italic", html)

    def test_calendar_supports_month_week_and_day_views(self):
        client, _ = self._client_for(self.admin)
        for mode, label, view_label in (
            ("month", "Август 2026", "Месяц"),
            ("week", "24–30 августа 2026", "Неделя"),
            ("day", "28 августа 2026", "День"),
        ):
            page = client.get(
                f"/notes?view=calendar&mode={mode}&selected=2026-08-28"
            )
            self.assertEqual(page.status_code, 200)
            html = page.get_data(as_text=True)
            self.assertIn(label, html)
            self.assertRegex(
                html, rf'class="view active"[^>]*>{view_label}</a>'
            )
            self.assertIn('class="icon-button new-event-button"', html)
            self.assertIn('aria-label="Новая заметка"', html)
            self.assertNotIn('</svg>Новая заметка</button>', html)

    def test_records_workspace_and_dictionary_placeholder_are_visible(self):
        client, _ = self._client_for(self.admin)
        records = client.get("/notes?view=records").get_data(as_text=True)
        dictionary = client.get("/notes?view=dictionary").get_data(as_text=True)

        self.assertIn('class="section-tabs"', records)
        self.assertNotIn('class="notes-tree"', records)
        self.assertIn("Все записи", records)
        self.assertIn("Контакты", records)
        self.assertIn("Интервью", records)
        self.assertIn("Заметки", records)
        self.assertNotIn(">Совещания<", records)
        self.assertNotIn(">Черновики<", records)
        self.assertNotIn('name="is_draft"', records)
        self.assertIn('data-new-record', records)
        self.assertIn("Карточки и проверку знаний добавим", dictionary)

    def test_legacy_meetings_and_drafts_are_shown_as_notes(self):
        client, _ = self._client_for(self.admin)
        storage.list_personal_notes(self.admin["id"])
        with storage._connect() as connection:
            connection.executemany(
                """INSERT INTO personal_notes(
                       user_id, title, body, record_type, is_draft,
                       created_at, updated_at
                   ) VALUES (?, ?, '', ?, ?, '2026-09-15', '2026-09-15')""",
                (
                    (self.admin["id"], "Старое совещание", "meeting", 0),
                    (self.admin["id"], "Старый черновик", "contact", 1),
                ),
            )

        notes = client.get(
            "/notes?view=records&kind=note"
        ).get_data(as_text=True)

        self.assertIn("Старое совещание", notes)
        self.assertIn("Старый черновик", notes)
        self.assertNotIn("Черновик</span>", notes)

    def test_admin_creates_filters_pins_and_deletes_contact_record(self):
        client, token = self._client_for(self.admin)
        created = client.post(
            "/notes?view=records",
            data={
                "csrf_token": token,
                "action": "save_record",
                "record_type": "contact",
                "title": "Алексей Иванов",
                "body": "Комментарий по отношениям с Японией",
                "tags": "МИД, Япония",
                "organization": "Министерство иностранных дел",
                "position": "Советник",
                "phone": "+7 999 123-45-67",
                "email": "ivanov@example.ru",
                "languages": "Русский, японский",
                "last_contact_date": "2026-09-15",
                "is_pinned": "1",
                "return_kind": "all",
            },
        )
        self.assertEqual(created.status_code, 302)
        records = storage.list_personal_notes(self.admin["id"])
        self.assertEqual(len(records), 1)
        record = records[0]
        self.assertEqual(record["record_type"], "contact")
        self.assertEqual(record["organization"], "Министерство иностранных дел")
        self.assertEqual(record["is_pinned"], 1)

        page = client.get(
            "/notes?view=records&kind=contact&q=Иванов&tag=Япония"
        ).get_data(as_text=True)
        self.assertIn("Алексей Иванов", page)
        self.assertIn("ivanov@example.ru", page)
        self.assertIn("ЗАКРЕПЛЁННЫЕ", page)

        toggled = client.post(
            "/notes?view=records",
            data={
                "csrf_token": token,
                "action": "toggle_record_pin",
                "record_id": record["id"],
                "is_pinned": "0",
                "return_kind": "all",
            },
        )
        self.assertEqual(toggled.status_code, 302)
        self.assertEqual(
            storage.list_personal_notes(self.admin["id"])[0]["is_pinned"], 0
        )

        deleted = client.post(
            "/notes?view=records",
            data={
                "csrf_token": token,
                "action": "delete_record",
                "record_id": record["id"],
                "return_kind": "all",
            },
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertEqual(storage.list_personal_notes(self.admin["id"]), [])

    def test_record_validation_rejects_unknown_type(self):
        client, token = self._client_for(self.admin)
        response = client.post(
            "/notes?view=records",
            data={
                "csrf_token": token,
                "action": "save_record",
                "record_type": "unknown",
                "title": "Тест",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Некорректный тип записи",
            response.get_data(as_text=True),
        )

    def test_week_without_selected_date_opens_current_week(self):
        client, _ = self._client_for(self.admin)
        today = date.today()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)

        html = client.get(
            "/notes?view=calendar&mode=week"
        ).get_data(as_text=True)

        self.assertIn(f'data-date="{today.isoformat()}"', html)
        self.assertIn(f"{week_start.day}–{week_end.day}", html)

    def test_admin_reorders_all_day_events(self):
        client, token = self._client_for(self.admin)
        first = storage.save_calendar_event(
            self.admin["id"], "Первое", "2026-09-14"
        )
        second = storage.save_calendar_event(
            self.admin["id"], "Второе", "2026-09-14"
        )

        response = client.post(
            "/notes?view=calendar",
            data={
                "csrf_token": token,
                "action": "reorder_events",
                "event_date": "2026-09-14",
                "event_id": [second, first],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"status": "ok"})
        events = storage.list_calendar_events(
            self.admin["id"], "2026-09-14", "2026-09-14"
        )
        self.assertEqual(
            [event["title"] for event in events],
            ["Второе", "Первое"],
        )

    def test_day_view_places_all_day_events_above_timeline(self):
        client, _ = self._client_for(self.admin)
        storage.save_calendar_event(
            self.admin["id"], "Главное событие", "2026-09-14"
        )

        html = client.get(
            "/notes?view=calendar&mode=day&selected=2026-09-14"
        ).get_data(as_text=True)

        self.assertLess(html.index("Главное событие"), html.index("09:00"))
        self.assertNotIn("На весь день", html)
        self.assertNotIn("Без времени", html)
        self.assertNotIn("day-aside", html)


if __name__ == "__main__":
    unittest.main()
