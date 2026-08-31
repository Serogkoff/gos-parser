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
        )
        storage.save_calendar_event(
            self.owner["id"],
            "Перенесённая встреча",
            "2026-09-02",
            "14:00",
            event_id=event_id,
        )
        events = storage.list_calendar_events(
            self.owner["id"], "2026-09-01", "2026-09-30"
        )
        self.assertEqual(events[0]["title"], "Перенесённая встреча")

        storage.delete_calendar_event(self.owner["id"], event_id)
        self.assertEqual(
            storage.list_calendar_events(
                self.owner["id"], "2026-09-01", "2026-09-30"
            ),
            [],
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
        self.assertEqual(
            storage.list_dictionary_cards(self.reader["id"], deck_id), []
        )


if __name__ == "__main__":
    unittest.main()
