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

    def test_records_workspace_and_dictionary_are_visible(self):
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
        self.assertIn("Словарь", dictionary)
        self.assertIn("Повторение", dictionary)
        self.assertIn("Статистика", dictionary)
        self.assertIn("Поиск по словарям", dictionary)
        self.assertIn('data-deck-search placeholder="Поиск"', dictionary)
        self.assertNotIn("Все словари", dictionary)
        self.assertNotIn('class="decks-new"', dictionary)
        self.assertIn("Создать словарь", dictionary)
        self.assertIn("Политика", dictionary)
        self.assertEqual(
            len(storage.list_dictionary_cards(
                self.admin["id"],
                storage.list_dictionary_decks(self.admin["id"])[0]["id"],
            )),
            30,
        )
        deck = storage.list_dictionary_decks(self.admin["id"])[0]
        inner = client.get(
            f"/notes?view=dictionary&mode=dictionary&deck={deck['id']}"
        ).get_data(as_text=True)
        self.assertIn("政府", inner)
        self.assertIn("правительство", inner)
        self.assertIn('data-speak="政府"', inner)
        self.assertIn('placeholder="Поиск"', inner)
        self.assertNotIn("<h1>Словарь</h1>", inner)
        self.assertNotIn('class="dictionary-page-head"', inner)
        self.assertIn('<summary aria-label="Фильтры" title="Фильтры">', inner)
        self.assertNotIn(">Фильтры</summary>", inner)
        self.assertIn('aria-label="Добавить термин"', inner)
        self.assertIn('class="dictionary-list-tools"', inner)
        self.assertIn('aria-label="Изменить выбранный термин"', inner)
        self.assertIn('aria-label="Удалить выбранный термин"', inner)
        self.assertNotIn("30 терминов", inner)
        self.assertNotIn(
            'class="dictionary-icon-action" type="button" '
            'data-new-dictionary-card',
            inner,
        )
        self.assertNotIn('class="detail-button delete-detail"', inner)
        self.assertNotIn(">Добавить</button>", inner)
        self.assertIn('aria-label="Начать квиз"', inner)
        self.assertIn('class="dictionary-quiz-count">30</span>', inner)

        quiz = client.get(
            f"/notes?view=dictionary&mode=quiz&deck={deck['id']}"
        ).get_data(as_text=True)
        self.assertIn('class="quiz-answer" data-quiz-answer hidden', quiz)
        self.assertNotIn('<h1>Квиз</h1>', quiz)
        self.assertIn('class="quiz-return-inline"', quiz)
        self.assertIn('class="quiz-ratings" data-quiz-ratings hidden', quiz)
        self.assertIn('data-quiz-rating="again">Снова</button>', quiz)
        self.assertNotIn('data-quiz-rating="again">1 ', quiz)

    def test_politics_demo_is_added_beside_an_existing_dictionary_once(self):
        storage.create_dictionary_deck(self.admin["id"], "Личный словарь")
        client, _ = self._client_for(self.admin)

        client.get("/notes?view=dictionary")
        client.get("/notes?view=dictionary")

        decks = storage.list_dictionary_decks(self.admin["id"])
        politics = next(deck for deck in decks if deck["name"] == "Политика")
        self.assertEqual(
            len(storage.list_dictionary_cards(self.admin["id"], politics["id"])),
            30,
        )

    def test_dictionary_search_card_actions_and_review(self):
        client, token = self._client_for(self.admin)
        client.get("/notes?view=dictionary")
        deck = storage.list_dictionary_decks(self.admin["id"])[0]
        cards = storage.list_dictionary_cards(self.admin["id"], deck["id"])
        card = next(item for item in cards if item["term"] == "選挙")

        search = client.get(
            f"/notes?view=dictionary&deck={deck['id']}&q=выборы"
        ).get_data(as_text=True)
        self.assertIn("選挙", search)
        self.assertNotIn("政府</span>", search)

        favorite = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "toggle_dictionary_favorite",
                "deck_id": deck["id"],
                "card_id": card["id"],
                "is_favorite": "1",
            },
        )
        self.assertEqual(favorite.status_code, 302)
        updated = storage.list_dictionary_cards(self.admin["id"], deck["id"])
        self.assertEqual(
            next(item for item in updated if item["id"] == card["id"])[
                "is_favorite"
            ],
            1,
        )

        reviewed = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "review_dictionary_card",
                "deck_id": deck["id"],
                "card_id": card["id"],
                "rating": "easy",
            },
            headers={"X-Requested-With": "fetch"},
        )
        self.assertEqual(reviewed.status_code, 200)
        self.assertEqual(reviewed.get_json()["interval_days"], 4)

    def test_dictionary_card_can_be_created_updated_and_deleted(self):
        client, token = self._client_for(self.admin)
        client.get("/notes?view=dictionary")
        deck = storage.list_dictionary_decks(self.admin["id"])[0]
        created = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "save_dictionary_card",
                "deck_id": deck["id"],
                "term": "条約",
                "reading": "じょうやく",
                "translation": "договор",
                "language": "ja",
                "tags": "Дипломатия",
                "example": "両国は条約に署名した。",
                "example_translation": "Две страны подписали договор.",
            },
        )
        self.assertEqual(created.status_code, 302)
        cards = storage.list_dictionary_cards(self.admin["id"], deck["id"])
        card = next(item for item in cards if item["term"] == "条約")
        self.assertEqual(card["tags"], "Дипломатия")

        deleted = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "delete_dictionary_card",
                "deck_id": deck["id"],
                "card_id": card["id"],
            },
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertNotIn(
            card["id"],
            [item["id"] for item in storage.list_dictionary_cards(
                self.admin["id"], deck["id"]
            )],
        )

    def test_dictionary_deck_can_be_created_renamed_and_deleted(self):
        client, token = self._client_for(self.admin)
        client.get("/notes?view=dictionary")
        created = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "save_dictionary_deck",
                "name": "Экономика",
            },
        )
        self.assertEqual(created.status_code, 302)
        deck = next(
            item for item in storage.list_dictionary_decks(self.admin["id"])
            if item["name"] == "Экономика"
        )

        renamed = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "save_dictionary_deck",
                "deck_id": deck["id"],
                "name": "Мировая экономика",
            },
        )
        self.assertEqual(renamed.status_code, 302)
        self.assertIn(
            "Мировая экономика",
            [item["name"] for item in storage.list_dictionary_decks(
                self.admin["id"]
            )],
        )

        deleted = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "delete_dictionary_deck",
                "deck_id": deck["id"],
            },
        )
        self.assertEqual(deleted.status_code, 302)
        self.assertNotIn(
            "Мировая экономика",
            [item["name"] for item in storage.list_dictionary_decks(
                self.admin["id"]
            )],
        )

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
