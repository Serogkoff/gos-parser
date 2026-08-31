"""Хранилище заметок, календаря и личных словарей."""

import sqlite3
from datetime import datetime, timedelta


def _validated_notes_text(value, field, maximum, required=False):
    text = str(value or "").strip()
    if required and not text:
        raise ValueError(f"Заполните поле «{field}»")
    if len(text) > maximum:
        raise ValueError(f"Поле «{field}» слишком длинное")
    return text


def _validated_visibility(value):
    visibility = str(value or "private").strip().casefold()
    if visibility not in {"private", "selected", "all"}:
        raise ValueError("Некорректный режим доступа")
    return visibility


def _validated_date(value, field="Дата"):
    text = str(value or "").strip()
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as error:
        raise ValueError(f"Поле «{field}» заполнено неверно") from error
    return text


def _validated_time(value):
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        datetime.strptime(text, "%H:%M")
    except ValueError as error:
        raise ValueError("Поле «Время» заполнено неверно") from error
    return text


def _replace_notes_shares(connection, table, owner_id, item_id, visibility,
                          shared_user_ids):
    id_column = "note_id" if table == "personal_note_shares" else "event_id"
    connection.execute(f"DELETE FROM {table} WHERE {id_column} = ?", (item_id,))
    if visibility != "selected":
        return
    result = set()
    for value in shared_user_ids or []:
        try:
            user_id = int(value)
        except (TypeError, ValueError):
            continue
        if user_id > 0 and user_id != owner_id:
            result.add(user_id)
    if not result:
        return
    available = {
        int(row["id"])
        for row in connection.execute(
            "SELECT id FROM users WHERE is_active = 1"
        ).fetchall()
    }
    connection.executemany(
        f"INSERT INTO {table}({id_column}, user_id) VALUES (?, ?)",
        [(item_id, user_id) for user_id in sorted(result & available)],
    )


def _shared_users(connection, table, id_column, item_id):
    rows = connection.execute(
        f"""SELECT u.id, u.username FROM {table} AS s
            JOIN users AS u ON u.id = s.user_id
            WHERE s.{id_column} = ? ORDER BY u.username COLLATE NOCASE""",
        (item_id,),
    ).fetchall()
    return [{"id": int(row["id"]), "username": row["username"]} for row in rows]


class PersonalWorkspaceStorage:
    def __init__(
        self, initialize_database, connection_factory, lock, validate_user_id
    ):
        self._initialize_database = initialize_database
        self._connection_factory = connection_factory
        self._lock = lock
        self._validate_user_id = validate_user_id

    def save_personal_note(self, user_id, folder, title, body, visibility="private",
                           shared_user_ids=None, note_id=None):
        """Создаёт или обновляет рабочую запись владельца."""
        user_id = self._validate_user_id(user_id)
        folder = _validated_notes_text(folder, "Папка", 80) or "Без папки"
        title = _validated_notes_text(title, "Заголовок", 200, required=True)
        body = _validated_notes_text(body, "Текст", 20_000)
        visibility = _validated_visibility(visibility)
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            if note_id:
                try:
                    note_id = int(note_id)
                except (TypeError, ValueError) as error:
                    raise ValueError("Заметка не найдена") from error
                cursor = connection.execute(
                    """UPDATE personal_notes
                       SET folder = ?, title = ?, body = ?, visibility = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
                    (folder, title, body, visibility, now, note_id, user_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Заметка не найдена")
            else:
                cursor = connection.execute(
                    """INSERT INTO personal_notes(
                           user_id, folder, title, body, visibility, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, folder, title, body, visibility, now, now),
                )
                note_id = cursor.lastrowid
            _replace_notes_shares(
                connection, "personal_note_shares", user_id, note_id,
                visibility, shared_user_ids,
            )
        return int(note_id)

    def list_personal_notes(self, user_id):
        """Возвращает личные записи владельца с настройкой доступа."""
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT id, folder, title, body, visibility, created_at, updated_at
                   FROM personal_notes WHERE user_id = ?
                   ORDER BY updated_at DESC, id DESC""",
                (user_id,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["id"] = int(item["id"])
                item["shared_users"] = _shared_users(
                    connection, "personal_note_shares", "note_id", item["id"]
                )
                result.append(item)
        return result

    def delete_personal_note(self, user_id, note_id):
        user_id = self._validate_user_id(user_id)
        try:
            note_id = int(note_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Заметка не найдена") from error
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                "DELETE FROM personal_notes WHERE id = ? AND user_id = ?",
                (note_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Заметка не найдена")

    def save_calendar_event(self, user_id, title, event_date, event_time="", place="",
                            description="", visibility="private",
                            shared_user_ids=None, event_id=None):
        """Создаёт или обновляет событие календаря владельца."""
        user_id = self._validate_user_id(user_id)
        title = _validated_notes_text(title, "Название", 200, required=True)
        event_date = _validated_date(event_date)
        event_time = _validated_time(event_time)
        place = _validated_notes_text(place, "Место", 500)
        description = _validated_notes_text(description, "Комментарий", 5000)
        visibility = _validated_visibility(visibility)
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            if event_id:
                try:
                    event_id = int(event_id)
                except (TypeError, ValueError) as error:
                    raise ValueError("Мероприятие не найдено") from error
                cursor = connection.execute(
                    """UPDATE calendar_events SET title = ?, event_date = ?,
                           event_time = ?, place = ?, description = ?, visibility = ?,
                           updated_at = ? WHERE id = ? AND user_id = ?""",
                    (title, event_date, event_time, place, description, visibility,
                     now, event_id, user_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Мероприятие не найдено")
            else:
                cursor = connection.execute(
                    """INSERT INTO calendar_events(
                           user_id, title, event_date, event_time, place, description,
                           visibility, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, title, event_date, event_time, place, description,
                     visibility, now, now),
                )
                event_id = cursor.lastrowid
            _replace_notes_shares(
                connection, "calendar_event_shares", user_id, event_id,
                visibility, shared_user_ids,
            )
        return int(event_id)

    def list_calendar_events(self, user_id, date_from, date_to):
        """Возвращает события владельца за включительный диапазон дат."""
        user_id = self._validate_user_id(user_id)
        date_from = _validated_date(date_from, "Начальная дата")
        date_to = _validated_date(date_to, "Конечная дата")
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT id, title, event_date, event_time, place, description,
                          visibility, created_at, updated_at
                   FROM calendar_events
                   WHERE user_id = ? AND event_date BETWEEN ? AND ?
                   ORDER BY event_date, event_time, id""",
                (user_id, date_from, date_to),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["id"] = int(item["id"])
                item["shared_users"] = _shared_users(
                    connection, "calendar_event_shares", "event_id", item["id"]
                )
                result.append(item)
        return result

    def delete_calendar_event(self, user_id, event_id):
        user_id = self._validate_user_id(user_id)
        try:
            event_id = int(event_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Мероприятие не найдено") from error
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                "DELETE FROM calendar_events WHERE id = ? AND user_id = ?",
                (event_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Мероприятие не найдено")

    def create_dictionary_deck(self, user_id, name):
        user_id = self._validate_user_id(user_id)
        name = _validated_notes_text(name, "Название словаря", 100, required=True)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock, self._connection_factory() as connection:
                cursor = connection.execute(
                    """INSERT INTO dictionary_decks(user_id, name, created_at, updated_at)
                       VALUES (?, ?, ?, ?)""",
                    (user_id, name, now, now),
                )
                deck_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise ValueError("Словарь с таким названием уже существует") from error
        return int(deck_id)

    def list_dictionary_decks(self, user_id):
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        today = datetime.now().date().isoformat()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT d.id, d.name, COUNT(c.id) AS card_count,
                          SUM(CASE WHEN c.id IS NOT NULL AND
                              (c.next_review = '' OR c.next_review <= ?) THEN 1 ELSE 0 END)
                              AS due_count
                   FROM dictionary_decks AS d
                   LEFT JOIN dictionary_cards AS c ON c.deck_id = d.id
                   WHERE d.user_id = ? GROUP BY d.id
                   ORDER BY d.name COLLATE NOCASE""",
                (today, user_id),
            ).fetchall()
        return [
            {"id": int(row["id"]), "name": row["name"],
             "card_count": int(row["card_count"] or 0),
             "due_count": int(row["due_count"] or 0)}
            for row in rows
        ]

    def save_dictionary_card(self, user_id, deck_id, term, reading, translation):
        user_id = self._validate_user_id(user_id)
        try:
            deck_id = int(deck_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Словарь не найден") from error
        term = _validated_notes_text(term, "Слово", 200, required=True)
        reading = _validated_notes_text(reading, "Чтение", 300)
        translation = _validated_notes_text(
            translation, "Перевод", 1000, required=True
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            if connection.execute(
                "SELECT 1 FROM dictionary_decks WHERE id = ? AND user_id = ?",
                (deck_id, user_id),
            ).fetchone() is None:
                raise ValueError("Словарь не найден")
            cursor = connection.execute(
                """INSERT INTO dictionary_cards(
                       deck_id, user_id, term, reading, translation, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (deck_id, user_id, term, reading, translation, now, now),
            )
            connection.execute(
                "UPDATE dictionary_decks SET updated_at = ? WHERE id = ?", (now, deck_id)
            )
        return int(cursor.lastrowid)

    def list_dictionary_cards(self, user_id, deck_id, due_only=False):
        user_id = self._validate_user_id(user_id)
        try:
            deck_id = int(deck_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Словарь не найден") from error
        today = datetime.now().date().isoformat()
        self._initialize_database()
        query = """SELECT c.id, c.deck_id, c.term, c.reading, c.translation,
                          c.repetitions, c.interval_days, c.next_review
                   FROM dictionary_cards AS c
                   JOIN dictionary_decks AS d ON d.id = c.deck_id
                   WHERE c.user_id = ? AND c.deck_id = ? AND d.user_id = ?"""
        parameters = [user_id, deck_id, user_id]
        if due_only:
            query += " AND (c.next_review = '' OR c.next_review <= ?)"
            parameters.append(today)
        query += " ORDER BY c.next_review, c.id"
        with self._connection_factory() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [dict(row) for row in rows]

    def review_dictionary_card(self, user_id, card_id, rating):
        """Применяет простой интервальный повтор для ответа в квизе."""
        user_id = self._validate_user_id(user_id)
        try:
            card_id = int(card_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Карточка не найдена") from error
        rating = str(rating or "").strip().casefold()
        if rating not in {"again", "hard", "good", "easy"}:
            raise ValueError("Неизвестная оценка карточки")
        with self._lock, self._connection_factory() as connection:
            row = connection.execute(
                """SELECT repetitions, interval_days FROM dictionary_cards
                   WHERE id = ? AND user_id = ?""",
                (card_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("Карточка не найдена")
            old_interval = int(row["interval_days"] or 0)
            old_repetitions = int(row["repetitions"] or 0)
            if rating == "again":
                repetitions, interval_days = 0, 0
            elif rating == "hard":
                repetitions, interval_days = old_repetitions + 1, max(1, old_interval)
            elif rating == "good":
                repetitions = old_repetitions + 1
                interval_days = 1 if old_interval == 0 else max(2, round(old_interval * 2.3))
            else:
                repetitions = old_repetitions + 1
                interval_days = 4 if old_interval == 0 else max(4, round(old_interval * 3.2))
            next_review = (
                datetime.now().date() + timedelta(days=interval_days)
            ).isoformat()
            connection.execute(
                """UPDATE dictionary_cards SET repetitions = ?, interval_days = ?,
                       next_review = ?, updated_at = ? WHERE id = ? AND user_id = ?""",
                (repetitions, interval_days, next_review,
                 datetime.now().isoformat(timespec="seconds"), card_id, user_id),
            )
        return {"id": card_id, "interval_days": interval_days,
                "next_review": next_review}
