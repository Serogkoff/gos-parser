import gc
import json
import tempfile
import unittest
from datetime import date, timedelta
from io import BytesIO
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

    def test_regular_user_gets_notes_and_calendar_but_dictionary_needs_access(self):
        client, _ = self._client_for(self.reader)

        self.assertEqual(client.get("/notes").status_code, 200)
        self.assertEqual(client.get("/notes?view=records").status_code, 200)
        self.assertEqual(client.get("/notes?view=dictionary").status_code, 403)
        with patch.object(web_app, "load_json", side_effect=self._empty_app_data):
            page = client.get("/")
        self.assertEqual(page.status_code, 200)
        html = page.get_data(as_text=True)
        self.assertIn('href="/notes"', html)
        self.assertIn('/notes?view=records', html)
        self.assertIn('/notes?view=calendar', html)
        self.assertNotIn('/notes?view=dictionary', html)
        self.assertNotIn('/admin/users', html)
        self.assertNotIn('/admin/system', html)

        storage.set_user_dictionary_access(self.reader["id"], True)
        client, _ = self._client_for(storage.load_user(self.reader["id"]))
        self.assertEqual(client.get("/notes?view=dictionary").status_code, 200)
        self.assertEqual(client.get("/admin/users").status_code, 403)
        self.assertEqual(client.get("/admin/system").status_code, 403)

    def test_admin_creates_event_and_opens_selected_day(self):
        client, token = self._client_for(self.admin)
        response = client.post(
            "/notes?view=calendar",
            data={
                "csrf_token": token,
                "action": "save_event",
                "title": "Встреча в МИД",
                "event_date": "2026-08-28",
                "end_date": "2026-08-28",
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
        self.assertIn('class="day-number mobile-day-number"', html)
        self.assertIn('class="mobile-calendar-agenda"', html)
        self.assertIn('<details class="mobile-past-agenda" open>', html)
        self.assertIn('<summary>Прошедшие события</summary>', html)
        self.assertIn('id="agenda-2026-08-28"', html)
        self.assertIn('class="mobile-agenda-event color-green event-bold event-italic ', html)
        self.assertIn('<time>14:00</time>', html)
        self.assertIn('class="mobile-calendar-add"', html)
        self.assertIn('class="mobile-bottom-nav"', html)
        self.assertIn('</svg><span>Записи</span></a>', html)

    def test_common_period_event_is_visible_but_only_owner_can_edit(self):
        owner_client, owner_token = self._client_for(self.admin)
        response = owner_client.post(
            "/notes?view=calendar",
            data={
                "csrf_token": owner_token,
                "action": "save_event",
                "title": "Отпуск редактора",
                "event_date": "2026-09-10",
                "end_date": "2026-09-16",
                "is_shared": "1",
                "color": "green",
                "calendar_mode": "month",
            },
        )
        self.assertEqual(response.status_code, 302)
        event = storage.list_calendar_events(
            self.admin["id"], "2026-09-10", "2026-09-16"
        )[0]
        self.assertEqual(event["visibility"], "all")
        self.assertEqual(event["end_date"], "2026-09-16")

        owner_html = owner_client.get(
            "/notes?view=calendar&mode=month&selected=2026-09-10"
        ).get_data(as_text=True)
        self.assertGreaterEqual(owner_html.count("Отпуск редактора"), 7)
        self.assertIn(f"event={event['id']}", owner_html)

        reader_client, _ = self._client_for(self.reader)
        reader_html = reader_client.get(
            "/notes?view=calendar&mode=day&selected=2026-09-12"
        ).get_data(as_text=True)
        self.assertIn("Отпуск редактора", reader_html)
        self.assertIn("Общее · owner", reader_html)
        self.assertIn("shared-event", reader_html)
        self.assertNotIn(f"event={event['id']}", reader_html)

    def test_mobile_calendar_starts_with_today_and_hides_past_events(self):
        class FixedDate(date):
            @classmethod
            def today(cls):
                return cls(2026, 9, 23)

        client, _ = self._client_for(self.admin)
        storage.save_calendar_event(
            self.admin["id"], "Прошедшее событие", "2026-09-22", color="blue"
        )
        storage.save_calendar_event(
            self.admin["id"], "Событие сегодня", "2026-09-23", color="green"
        )
        storage.save_calendar_event(
            self.admin["id"], "Будущее событие", "2026-09-24", color="violet"
        )

        with patch.object(web_app, "date", FixedDate):
            html = client.get(
                "/notes?view=calendar&mode=month&selected=2026-09-23"
            ).get_data(as_text=True)

        agenda_start = html.index('<div class="mobile-calendar-agenda">')
        details_start = html.index('<details class="mobile-past-agenda"')
        details_end = html.index("</details>", details_start)
        opening_tag = html[details_start:html.index(">", details_start) + 1]
        upcoming_html = html[agenda_start:details_start]
        past_html = html[details_start:details_end]

        self.assertIn("Событие сегодня", upcoming_html)
        self.assertIn("Будущее событие", upcoming_html)
        self.assertNotIn("Прошедшее событие", upcoming_html)
        self.assertIn("Прошедшее событие", past_html)
        self.assertNotIn(" open", opening_tag)

    def test_calendar_supports_month_week_and_day_views(self):
        client, _ = self._client_for(self.admin)
        stylesheet = (
            Path(web_app.app.static_folder) / "notes.css"
        ).read_text(encoding="utf-8")
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
            self.assertIn('aria-label="Новое событие"', html)
            self.assertNotIn('</svg>Новое событие</button>', html)
            self.assertIn('.new-event-button,.record-add', stylesheet)

        for marker in (
            '.mobile-bottom-nav,.mobile-day-number,.mobile-event-dots',
            '.clocks{grid-column:1;grid-row:2;width:auto',
            'display:flex!important',
            '.head-actions{display:none}',
            '.month{min-width:0',
            '.mobile-calendar-agenda{padding:20px 0 4px;display:grid',
            '.mobile-past-agenda summary{min-height:44px',
            '.event-chip,.week-event,.day-event,.aside-event,.mobile-agenda-event{--event-fill:#fff1ee',
            '.mobile-calendar-add{position:fixed',
            'grid-template-columns:repeat(5,minmax(0,1fr))',
        ):
            with self.subTest(mobile_calendar_marker=marker):
                self.assertIn(marker, stylesheet)
        self.assertNotIn('.mobile-agenda-event{--event-line:#e9362a', stylesheet)

    def test_records_workspace_and_dictionary_are_visible(self):
        client, _ = self._client_for(self.admin)
        stylesheet = (
            Path(web_app.app.static_folder) / "notes.css"
        ).read_text(encoding="utf-8")
        records = client.get("/notes?view=records").get_data(as_text=True)
        dictionary = client.get("/notes?view=dictionary").get_data(as_text=True)

        self.assertIn('class="section-tabs"', records)
        self.assertNotIn('class="notes-tree"', records)
        self.assertIn("Все записи", records)
        self.assertIn("Контакты", records)
        self.assertIn("Интервью", records)
        self.assertIn("Заметки", records)
        self.assertIn('</svg></span>Заметки</a>', records)
        self.assertIn('</svg><span>Записи</span></a>', records)
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
        self.assertIn('aria-label="Импортировать JSON"', inner)
        self.assertIn('id="dictionary-import-dialog"', inner)
        self.assertIn('name="dictionary_file"', inner)
        self.assertIn('class="dictionary-list-tools"', inner)
        self.assertIn('data-mobile-dictionary-card', inner)
        self.assertIn('data-mobile-open="false"', inner)
        self.assertIn('data-dictionary-card-link', inner)
        self.assertIn('data-mobile-dictionary-position', inner)
        self.assertIn('data-mobile-dictionary-previous', inner)
        self.assertIn('data-mobile-dictionary-next', inner)
        self.assertIn('Свайпните влево или вправо', inner)
        self.assertIn("Math.abs(dx)<60", inner)
        self.assertIn('body.mobile-dictionary-card-open{overflow:hidden}', stylesheet)
        self.assertIn("const preloadCard=index=>", inner)
        self.assertIn("preloadCard(current+1)", inner)
        self.assertIn("preloadCard(current+2)", inner)
        self.assertIn("mobileDictionaryCard.innerHTML=data.innerHTML", inner)
        self.assertIn("history.replaceState", inner)
        self.assertIn("event.preventDefault();openSibling(index)", inner)
        self.assertIn("const syncSelectedActions=data=>", inner)
        self.assertNotIn("if(!target||!mobileMedia.matches)", inner)
        self.assertNotIn('transition:opacity', stylesheet)
        self.assertNotIn('translateX(', stylesheet)
        self.assertIn('aria-label="Изменить выбранный термин"', inner)
        self.assertIn('aria-label="Удалить выбранный термин"', inner)
        self.assertNotIn("30 терминов", inner)
        self.assertNotIn(
            'class="dictionary-icon-action" type="button" '
            'data-new-dictionary-card',
            inner,
        )
        self.assertNotIn('class="detail-button delete-detail"', inner)
        self.assertIn('.dictionary-bookmark-form{display:none}', stylesheet)
        self.assertIn(
            "['term','reading','translation','tags','notes'].forEach", inner
        )
        self.assertIn('name="example_text"', inner)
        self.assertIn('name="example_translation"', inner)
        self.assertIn('data-add-example', inner)
        self.assertIn('data-remove-example', inner)
        self.assertNotIn('name="source"', inner)
        self.assertNotIn("<h2>Источник</h2>", inner)
        self.assertIn("form.elements.language.value='ja'", inner)
        self.assertNotIn(">Добавить</button>", inner)
        self.assertIn('aria-label="Начать квиз"', inner)
        self.assertIn('class="dictionary-quiz-count">30</span>', inner)

        first_card = storage.list_dictionary_cards(
            self.admin["id"], deck["id"]
        )[0]
        mobile_card = client.get(
            f"/notes?view=dictionary&mode=dictionary&deck={deck['id']}"
            f"&card={first_card['id']}"
        ).get_data(as_text=True)
        self.assertIn('data-mobile-open="true"', mobile_card)
        self.assertIn('class="mobile-dictionary-card-open"', mobile_card)
        self.assertNotIn('class="mobile-dictionary-card-open"', inner)

        quiz = client.get(
            f"/notes?view=dictionary&mode=quiz&deck={deck['id']}"
        ).get_data(as_text=True)
        self.assertIn('class="quiz-answer" data-quiz-answer hidden', quiz)
        self.assertNotIn('<h1>Квиз</h1>', quiz)
        self.assertIn('class="quiz-return-inline"', quiz)
        self.assertIn('class="quiz-ratings" data-quiz-ratings hidden', quiz)
        self.assertIn('data-quiz-rating="again">Снова</button>', quiz)
        self.assertNotIn('data-quiz-rating="again">1 ', quiz)

    def test_dictionary_cards_can_be_imported_from_json(self):
        client, token = self._client_for(self.admin)
        deck_id = storage.create_dictionary_deck(self.admin["id"], "Выборы")
        payload = {
            "source": "共同通信・選挙記事",
            "cards": [
                {
                    "term": "下院選", "reading": "かいんせん",
                    "translation": "выборы в нижнюю палату",
                    "tags": ["Выборы", "Политика"],
                    "examples": [
                        {"text": "下院選が始まる。", "translation": "Начинаются выборы."},
                        {"text": "下院選を報じる。", "translation": "Сообщать о выборах."},
                    ],
                },
                {
                    "term": "議席", "reading": "ぎせき",
                    "translation": "депутатское место",
                },
            ],
        }
        response = client.post(
            "/notes?view=dictionary&mode=dictionary",
            data={
                "csrf_token": token,
                "action": "import_dictionary_cards",
                "deck_id": str(deck_id),
                "dictionary_file": (
                    BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                    "elections.json",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Импортировано карточек: 2", html)
        cards = storage.list_dictionary_cards(self.admin["id"], deck_id)
        self.assertEqual({card["term"] for card in cards}, {"下院選", "議席"})
        self.assertTrue(all(card["source"] == "共同通信・選挙記事" for card in cards))
        imported = next(card for card in cards if card["term"] == "下院選")
        self.assertEqual(len(imported["examples"]), 2)
        self.assertEqual(imported["examples"][1]["translation"], "Сообщать о выборах.")

        duplicate = client.post(
            "/notes?view=dictionary&mode=dictionary",
            data={
                "csrf_token": token,
                "action": "import_dictionary_cards",
                "deck_id": str(deck_id),
                "dictionary_file": (
                    BytesIO(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                    "elections.json",
                ),
            },
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        self.assertIn(
            "дубликатов пропущено: 2", duplicate.get_data(as_text=True)
        )

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
                "example_text": ["両国は条約に署名した。", "条約が発効した。"],
                "example_translation": [
                    "Две страны подписали договор.", "Договор вступил в силу.",
                ],
            },
        )
        self.assertEqual(created.status_code, 302)
        cards = storage.list_dictionary_cards(self.admin["id"], deck["id"])
        card = next(item for item in cards if item["term"] == "条約")
        self.assertEqual(card["tags"], "Дипломатия")
        self.assertEqual(card["examples"], [
            {"text": "両国は条約に署名した。", "translation": "Две страны подписали договор."},
            {"text": "条約が発効した。", "translation": "Договор вступил в силу."},
        ])
        detail = client.get(
            f"/notes?view=dictionary&mode=dictionary&deck={deck['id']}&card={card['id']}"
        ).get_data(as_text=True)
        self.assertIn("両国は条約に署名した。", detail)
        self.assertIn("条約が発効した。", detail)
        self.assertNotIn("<h2>Источник</h2>", detail)

        updated = client.post(
            "/notes?view=dictionary",
            data={
                "csrf_token": token,
                "action": "save_dictionary_card",
                "deck_id": deck["id"],
                "card_id": card["id"],
                "term": "条約",
                "reading": "じょうやく",
                "translation": "договор",
                "language": "ja",
                "tags": "Дипломатия",
                "example_text": ["新しい例。"],
                "example_translation": ["Новый пример."],
            },
        )
        self.assertEqual(updated.status_code, 302)
        card = next(
            item for item in storage.list_dictionary_cards(self.admin["id"], deck["id"])
            if item["id"] == card["id"]
        )
        self.assertEqual(
            card["examples"], [{"text": "新しい例。", "translation": "Новый пример."}]
        )

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

    def test_long_record_expands_inline_without_reloading(self):
        client, token = self._client_for(self.admin)
        body = "Начало " + ("подробный текст " * 30) + "конец записи"
        response = client.post(
            "/notes?view=records",
            data={
                "csrf_token": token,
                "action": "save_record",
                "record_type": "note",
                "title": "Длинная запись",
                "body": body,
                "return_kind": "all",
            },
        )
        self.assertEqual(response.status_code, 302)

        page = client.get("/notes?view=records").get_data(as_text=True)
        self.assertIn('data-record-toggle aria-expanded="false">Развернуть</button>', page)
        self.assertIn('data-record-full hidden', page)
        self.assertIn("конец записи", page)
        self.assertIn("button.textContent=expanded?'Развернуть':'Свернуть'", page)

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
