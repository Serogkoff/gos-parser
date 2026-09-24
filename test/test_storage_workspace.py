import gc
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import storage


class PersonalWorkspaceStorageTests(unittest.TestCase):
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
        self.owner = storage.create_user(
            "owner", "owner-secret-2026", role="admin"
        )
        self.reader = storage.create_user("reader", "reader-secret-2026")

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        gc.collect()
        self.temporary.cleanup()

    def test_note_can_be_shared_updated_and_deleted(self):
        note_id = storage.save_personal_note(
            self.owner["id"],
            "Контакты",
            "Пресс-центр",
            "+7 495 000-00-00",
            visibility="selected",
            shared_user_ids=[self.reader["id"]],
        )
        note = storage.list_personal_notes(self.owner["id"])[0]
        self.assertEqual(note["id"], note_id)
        self.assertEqual(note["shared_users"][0]["username"], "reader")

        storage.save_personal_note(
            self.owner["id"],
            "Контакты",
            "Пресс-центр МИД",
            note["body"],
            visibility="private",
            note_id=note_id,
        )
        updated = storage.list_personal_notes(self.owner["id"])[0]
        self.assertEqual(updated["title"], "Пресс-центр МИД")
        self.assertEqual(updated["shared_users"], [])

        storage.delete_personal_note(self.owner["id"], note_id)
        self.assertEqual(storage.list_personal_notes(self.owner["id"]), [])

    def test_calendar_event_can_be_updated_and_deleted(self):
        event_id = storage.save_calendar_event(
            self.owner["id"],
            "Встреча",
            "2026-09-01",
            "12:30",
            place="Москва",
            color="blue",
        )
        storage.save_calendar_event(
            self.owner["id"],
            "Перенесённая встреча",
            "2026-09-02",
            "14:00",
            color="violet",
            is_bold=True,
            is_italic=True,
            event_id=event_id,
        )
        events = storage.list_calendar_events(
            self.owner["id"], "2026-09-01", "2026-09-30"
        )
        self.assertEqual(events[0]["title"], "Перенесённая встреча")
        self.assertEqual(events[0]["color"], "violet")
        self.assertEqual(events[0]["is_bold"], 1)
        self.assertEqual(events[0]["is_italic"], 1)

        storage.delete_calendar_event(self.owner["id"], event_id)
        self.assertEqual(
            storage.list_calendar_events(
                self.owner["id"], "2026-09-01", "2026-09-30"
            ),
            [],
        )

    def test_all_day_calendar_events_can_be_reordered(self):
        first = storage.save_calendar_event(
            self.owner["id"], "Первое", "2026-09-14"
        )
        second = storage.save_calendar_event(
            self.owner["id"], "Второе", "2026-09-14"
        )
        third = storage.save_calendar_event(
            self.owner["id"], "Третье", "2026-09-14"
        )

        storage.reorder_calendar_events(
            self.owner["id"], "2026-09-14", [third, first, second]
        )

        events = storage.list_calendar_events(
            self.owner["id"], "2026-09-14", "2026-09-14"
        )
        self.assertEqual(
            [event["title"] for event in events],
            ["Третье", "Первое", "Второе"],
        )

    def test_calendar_period_and_common_event_are_visible_to_other_users(self):
        common_id = storage.save_calendar_event(
            self.owner["id"], "Отпуск", "2026-09-10",
            visibility="all", color="green", end_date="2026-09-16",
        )
        storage.save_calendar_event(
            self.owner["id"], "Личное", "2026-09-12", end_date="2026-09-13",
        )

        reader_events = storage.list_calendar_events(
            self.reader["id"], "2026-09-12", "2026-09-12"
        )
        self.assertEqual([event["id"] for event in reader_events], [common_id])
        self.assertEqual(reader_events[0]["end_date"], "2026-09-16")
        self.assertEqual(reader_events[0]["owner_username"], "owner")
        self.assertTrue(reader_events[0]["is_shared"])
        self.assertFalse(reader_events[0]["can_edit"])

        owner_event = storage.list_calendar_events(
            self.owner["id"], "2026-09-16", "2026-09-16"
        )[0]
        self.assertTrue(owner_event["can_edit"])

    def test_calendar_period_cannot_end_before_it_starts(self):
        with self.assertRaisesRegex(ValueError, "раньше даты начала"):
            storage.save_calendar_event(
                self.owner["id"], "Ошибка", "2026-09-16",
                end_date="2026-09-10",
            )

    def test_dictionary_is_private_to_its_owner(self):
        deck_id = storage.create_dictionary_deck(self.owner["id"], "Политика")
        card_id = storage.save_dictionary_card(
            self.owner["id"],
            deck_id,
            "記者会見",
            "きしゃかいけん",
            "пресс-конференция",
        )
        reviewed = storage.review_dictionary_card(
            self.owner["id"], card_id, "easy"
        )
        self.assertEqual(reviewed["interval_days"], 4)
        activity = storage.dictionary_review_activity(self.owner["id"])
        self.assertEqual(sum(day["count"] for day in activity.values()), 1)
        self.assertEqual(
            storage.list_dictionary_cards(self.reader["id"], deck_id), []
        )

    def test_dictionary_import_is_atomic_and_skips_duplicates(self):
        deck_id = storage.create_dictionary_deck(self.owner["id"], "Выборы")
        storage.save_dictionary_card(
            self.owner["id"], deck_id, "議席", "ぎせき", "мандат"
        )
        result = storage.import_dictionary_cards(self.owner["id"], deck_id, [
            {"term": "議席", "reading": "ぎせき", "translation": "место"},
            {
                "term": "投票", "reading": "とうひょう",
                "translation": "голосование", "tags": ["Выборы", "N2"],
            },
            {"term": "投票", "reading": "とうひょう", "translation": "голос"},
        ])
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["skipped"], 2)
        cards = storage.list_dictionary_cards(self.owner["id"], deck_id)
        self.assertEqual({card["term"] for card in cards}, {"議席", "投票"})
        self.assertEqual(
            next(card for card in cards if card["term"] == "投票")["tags"],
            "Выборы, N2",
        )

        with self.assertRaisesRegex(ValueError, "Карточка 2"):
            storage.import_dictionary_cards(self.owner["id"], deck_id, [
                {"term": "政党", "reading": "せいとう", "translation": "партия"},
                {"term": "候補者", "reading": "こうほしゃ"},
            ])
        self.assertNotIn(
            "政党",
            {card["term"] for card in storage.list_dictionary_cards(
                self.owner["id"], deck_id
            )},
        )


if __name__ == "__main__":
    unittest.main()
