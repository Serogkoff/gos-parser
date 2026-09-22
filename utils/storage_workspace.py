"""Хранилище заметок, календаря и личных словарей."""

import sqlite3
from datetime import datetime, timedelta


POLITICS_DEMO_CARDS = (
    ("政府", "せいふ", "правительство", "Государство", "政府は新しい経済政策を発表した。", "Правительство объявило новую экономическую политику."),
    ("国会", "こっかい", "парламент Японии", "Государство", "法案は国会で審議される。", "Законопроект будет рассмотрен в парламенте."),
    ("衆議院", "しゅうぎいん", "Палата представителей", "Государство", "衆議院で予算案が可決された。", "Проект бюджета был одобрен Палатой представителей."),
    ("参議院", "さんぎいん", "Палата советников", "Государство", "参議院は法案の審議を始めた。", "Палата советников начала рассмотрение законопроекта."),
    ("内閣", "ないかく", "кабинет министров", "Правительство", "内閣は総辞職を決めた。", "Кабинет министров решил уйти в отставку в полном составе."),
    ("首相", "しゅしょう", "премьер-министр", "Правительство", "首相は記者会見を開いた。", "Премьер-министр провёл пресс-конференцию."),
    ("大統領", "だいとうりょう", "президент", "Государство", "両国の大統領が電話会談を行った。", "Президенты двух стран провели телефонные переговоры."),
    ("外務省", "がいむしょう", "министерство иностранных дел", "Дипломатия", "外務省は声明を発表した。", "Министерство иностранных дел опубликовало заявление."),
    ("与党", "よとう", "правящая партия", "Партии", "与党は法案への支持を呼びかけた。", "Правящая партия призвала поддержать законопроект."),
    ("野党", "やとう", "оппозиционная партия; оппозиция", "Партии", "野党は政府の対応を批判した。", "Оппозиция раскритиковала действия правительства."),
    ("連立政権", "れんりつせいけん", "коалиционное правительство", "Партии", "二つの政党が連立政権を樹立した。", "Две партии сформировали коалиционное правительство."),
    ("選挙", "せんきょ", "выборы", "Выборы", "来月、地方選挙が行われる。", "В следующем месяце пройдут местные выборы."),
    ("総選挙", "そうせんきょ", "всеобщие выборы", "Выборы", "政府は秋の総選挙を検討している。", "Правительство рассматривает проведение всеобщих выборов осенью."),
    ("投票", "とうひょう", "голосование; подача голоса", "Выборы", "投票は午後八時に締め切られた。", "Голосование завершилось в восемь часов вечера."),
    ("有権者", "ゆうけんしゃ", "избиратель; лицо с правом голоса", "Выборы", "候補者は有権者に支持を訴えた。", "Кандидат обратился к избирателям за поддержкой."),
    ("候補者", "こうほしゃ", "кандидат", "Выборы", "三人の候補者が選挙に立候補した。", "Три кандидата выдвинулись на выборы."),
    ("議席", "ぎせき", "депутатское место; мандат", "Выборы", "与党は過半数の議席を維持した。", "Правящая партия сохранила большинство мест."),
    ("法案", "ほうあん", "законопроект", "Законодательство", "政府は国会に法案を提出した。", "Правительство внесло законопроект в парламент."),
    ("予算案", "よさんあん", "проект бюджета", "Законодательство", "来年度の予算案が閣議決定された。", "Проект бюджета на следующий финансовый год был утверждён кабинетом."),
    ("政策", "せいさく", "политика; политический курс", "Правительство", "新しい政策の効果が議論されている。", "Обсуждается эффективность нового политического курса."),
    ("外交", "がいこう", "дипломатия; внешняя политика", "Дипломатия", "経済協力は外交の重要な柱だ。", "Экономическое сотрудничество — важная опора дипломатии."),
    ("安全保障", "あんぜんほしょう", "национальная безопасность", "Дипломатия", "両国は安全保障問題を協議した。", "Две страны обсудили вопросы безопасности."),
    ("制裁", "せいさい", "санкции", "Дипломатия", "政府は追加制裁を発表した。", "Правительство объявило дополнительные санкции."),
    ("首脳会談", "しゅのうかいだん", "саммит; встреча лидеров", "Дипломатия", "首脳会談は二時間にわたって行われた。", "Встреча лидеров продолжалась два часа."),
    ("記者会見", "きしゃかいけん", "пресс-конференция", "СМИ", "官房長官は記者会見で説明した。", "Генеральный секретарь кабинета дал пояснения на пресс-конференции."),
    ("世論調査", "よろんちょうさ", "опрос общественного мнения", "Общество", "最新の世論調査の結果が公表された。", "Опубликованы результаты последнего опроса общественного мнения."),
    ("支持率", "しじりつ", "рейтинг поддержки", "Общество", "内閣支持率は前月より低下した。", "Рейтинг поддержки кабинета снизился по сравнению с прошлым месяцем."),
    ("解散", "かいさん", "роспуск (парламента, палаты)", "Выборы", "首相は衆議院を解散した。", "Премьер-министр распустил Палату представителей."),
    ("辞任", "じにん", "отставка; уход с должности", "Правительство", "大臣は責任を取って辞任した。", "Министр взял на себя ответственность и ушёл в отставку."),
    ("就任", "しゅうにん", "вступление в должность", "Правительство", "新しい大臣が正式に就任した。", "Новый министр официально вступил в должность."),
)


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


def _validated_event_color(value):
    color = str(value or "red").strip().casefold()
    if color not in {"red", "blue", "green", "amber", "violet", "gray"}:
        raise ValueError("Некорректный цвет заметки")
    return color


def _validated_checkbox(value):
    return 1 if str(value or "").strip().casefold() in {
        "1", "true", "yes", "on",
    } else 0


def _validated_record_type(value):
    record_type = str(value or "note").strip().casefold()
    if record_type not in {"note", "contact", "interview"}:
        raise ValueError("Некорректный тип записи")
    return record_type


def _validated_optional_date(value, field):
    text = str(value or "").strip()
    return _validated_date(text, field) if text else ""


def _validated_dictionary_examples(examples):
    if examples is None:
        return []
    if not isinstance(examples, list):
        raise ValueError("Примеры должны быть списком")
    if len(examples) > 20:
        raise ValueError("В одной карточке может быть не больше 20 примеров")
    prepared = []
    for index, example in enumerate(examples, start=1):
        if not isinstance(example, dict):
            raise ValueError(f"Пример {index}: ожидался объект")
        text = _validated_notes_text(
            example.get("text", example.get("example")), "Пример", 2000
        )
        translation = _validated_notes_text(
            example.get("translation", example.get("example_translation")),
            "Перевод примера", 2000,
        )
        if not text and not translation:
            continue
        if not text:
            raise ValueError(f"Пример {index}: заполните текст примера")
        prepared.append({"text": text, "translation": translation})
    return prepared


def _replace_dictionary_examples(connection, card_id, examples):
    connection.execute(
        "DELETE FROM dictionary_examples WHERE card_id = ?", (card_id,)
    )
    connection.executemany(
        """INSERT INTO dictionary_examples(
               card_id, sort_order, example_text, translation
           ) VALUES (?, ?, ?, ?)""",
        (
            (card_id, sort_order, example["text"], example["translation"])
            for sort_order, example in enumerate(examples)
        ),
    )


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
                           shared_user_ids=None, note_id=None, record_type="note",
                           tags="", is_pinned=False, is_draft=False,
                           organization="", position="", phone="", email="",
                           languages="", last_contact_date=""):
        """Создаёт или обновляет рабочую запись владельца."""
        user_id = self._validate_user_id(user_id)
        folder = _validated_notes_text(folder, "Папка", 80) or "Без папки"
        title = _validated_notes_text(title, "Заголовок", 200, required=True)
        body = _validated_notes_text(body, "Текст", 20_000)
        visibility = _validated_visibility(visibility)
        record_type = _validated_record_type(record_type)
        tags = _validated_notes_text(tags, "Теги", 500)
        is_pinned = _validated_checkbox(is_pinned)
        is_draft = _validated_checkbox(is_draft)
        organization = _validated_notes_text(organization, "Организация", 300)
        position = _validated_notes_text(position, "Должность", 300)
        phone = _validated_notes_text(phone, "Телефон", 100)
        email = _validated_notes_text(email, "Email", 300)
        languages = _validated_notes_text(languages, "Языки", 300)
        last_contact_date = _validated_optional_date(
            last_contact_date, "Дата последнего контакта",
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            if note_id:
                try:
                    note_id = int(note_id)
                except (TypeError, ValueError) as error:
                    raise ValueError("Заметка не найдена") from error
                cursor = connection.execute(
                    """UPDATE personal_notes
                       SET folder = ?, title = ?, body = ?, visibility = ?,
                           record_type = ?, tags = ?, is_pinned = ?, is_draft = ?,
                           organization = ?, position = ?, phone = ?, email = ?,
                           languages = ?, last_contact_date = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
                    (folder, title, body, visibility, record_type, tags,
                     is_pinned, is_draft, organization, position, phone, email,
                     languages, last_contact_date, now, note_id, user_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Заметка не найдена")
            else:
                cursor = connection.execute(
                    """INSERT INTO personal_notes(
                           user_id, folder, title, body, visibility, record_type,
                           tags, is_pinned, is_draft, organization, position,
                           phone, email, languages, last_contact_date,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, folder, title, body, visibility, record_type,
                     tags, is_pinned, is_draft, organization, position, phone,
                     email, languages, last_contact_date, now, now),
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
                """SELECT id, folder, title, body, visibility, record_type, tags,
                          is_pinned, is_draft, organization, position, phone,
                          email, languages, last_contact_date, created_at, updated_at
                   FROM personal_notes WHERE user_id = ?
                   ORDER BY is_pinned DESC, updated_at DESC, id DESC""",
                (user_id,),
            ).fetchall()
            share_rows = connection.execute(
                """SELECT s.note_id, u.id, u.username
                   FROM personal_note_shares AS s
                   JOIN personal_notes AS n ON n.id = s.note_id
                   JOIN users AS u ON u.id = s.user_id
                   WHERE n.user_id = ?
                   ORDER BY u.username COLLATE NOCASE""",
                (user_id,),
            ).fetchall()
            shares_by_note = {}
            for row in share_rows:
                shares_by_note.setdefault(int(row["note_id"]), []).append({
                    "id": int(row["id"]), "username": row["username"],
                })
            result = []
            for row in rows:
                item = dict(row)
                item["id"] = int(item["id"])
                item["shared_users"] = shares_by_note.get(item["id"], [])
                result.append(item)
        return result

    def set_personal_note_pinned(self, user_id, note_id, is_pinned):
        user_id = self._validate_user_id(user_id)
        try:
            note_id = int(note_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Запись не найдена") from error
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                """UPDATE personal_notes SET is_pinned = ?
                   WHERE id = ? AND user_id = ?""",
                (_validated_checkbox(is_pinned), note_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Запись не найдена")

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
                            shared_user_ids=None, event_id=None, color="red",
                            is_bold=False, is_italic=False):
        """Создаёт или обновляет событие календаря владельца."""
        user_id = self._validate_user_id(user_id)
        title = _validated_notes_text(title, "Название", 200, required=True)
        event_date = _validated_date(event_date)
        event_time = _validated_time(event_time)
        place = _validated_notes_text(place, "Место", 500)
        description = _validated_notes_text(description, "Комментарий", 5000)
        visibility = _validated_visibility(visibility)
        color = _validated_event_color(color)
        is_bold = _validated_checkbox(is_bold)
        is_italic = _validated_checkbox(is_italic)
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            sort_order = 0
            if event_id:
                try:
                    event_id = int(event_id)
                except (TypeError, ValueError) as error:
                    raise ValueError("Мероприятие не найдено") from error
                current = connection.execute(
                    """SELECT event_date, event_time, sort_order
                       FROM calendar_events WHERE id = ? AND user_id = ?""",
                    (event_id, user_id),
                ).fetchone()
                if current is None:
                    raise ValueError("Мероприятие не найдено")
                if not event_time:
                    if current["event_date"] == event_date and not current["event_time"]:
                        sort_order = int(current["sort_order"])
                    else:
                        sort_order = self._next_calendar_sort_order(
                            connection, user_id, event_date,
                        )
                cursor = connection.execute(
                    """UPDATE calendar_events SET title = ?, event_date = ?,
                           event_time = ?, place = ?, description = ?, visibility = ?,
                           color = ?, is_bold = ?, is_italic = ?, sort_order = ?,
                           updated_at = ? WHERE id = ? AND user_id = ?""",
                    (title, event_date, event_time, place, description, visibility,
                     color, is_bold, is_italic, sort_order,
                     now, event_id, user_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Мероприятие не найдено")
            else:
                if not event_time:
                    sort_order = self._next_calendar_sort_order(
                        connection, user_id, event_date,
                    )
                cursor = connection.execute(
                    """INSERT INTO calendar_events(
                           user_id, title, event_date, event_time, place, description,
                           visibility, color, is_bold, is_italic, sort_order,
                           created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (user_id, title, event_date, event_time, place, description,
                     visibility, color, is_bold, is_italic, sort_order, now, now),
                )
                event_id = cursor.lastrowid
            _replace_notes_shares(
                connection, "calendar_event_shares", user_id, event_id,
                visibility, shared_user_ids,
            )
        return int(event_id)

    @staticmethod
    def _next_calendar_sort_order(connection, user_id, event_date):
        row = connection.execute(
            """SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order
               FROM calendar_events
               WHERE user_id = ? AND event_date = ? AND event_time = ''""",
            (user_id, event_date),
        ).fetchone()
        return int(row["next_order"])

    def list_calendar_events(self, user_id, date_from, date_to):
        """Возвращает события владельца за включительный диапазон дат."""
        user_id = self._validate_user_id(user_id)
        date_from = _validated_date(date_from, "Начальная дата")
        date_to = _validated_date(date_to, "Конечная дата")
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT id, title, event_date, event_time, place, description,
                          visibility, color, is_bold, is_italic, sort_order,
                          created_at, updated_at
                   FROM calendar_events
                   WHERE user_id = ? AND event_date BETWEEN ? AND ?
                   ORDER BY event_date,
                            CASE WHEN event_time = '' THEN 0 ELSE 1 END,
                            CASE WHEN event_time = '' THEN sort_order ELSE 0 END,
                            event_time, id""",
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

    def reorder_calendar_events(self, user_id, event_date, event_ids):
        """Сохраняет порядок всех событий без времени в одном дне."""
        user_id = self._validate_user_id(user_id)
        event_date = _validated_date(event_date)
        try:
            ordered_ids = [int(value) for value in event_ids]
        except (TypeError, ValueError) as error:
            raise ValueError("Не удалось изменить порядок заметок") from error
        if not ordered_ids or len(ordered_ids) != len(set(ordered_ids)):
            raise ValueError("Не удалось изменить порядок заметок")

        with self._lock, self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT id FROM calendar_events
                   WHERE user_id = ? AND event_date = ? AND event_time = ''""",
                (user_id, event_date),
            ).fetchall()
            available_ids = {int(row["id"]) for row in rows}
            if set(ordered_ids) != available_ids:
                raise ValueError("Список заметок изменился. Обновите страницу")
            connection.executemany(
                """UPDATE calendar_events SET sort_order = ?
                   WHERE id = ? AND user_id = ?""",
                [
                    (position, event_id, user_id)
                    for position, event_id in enumerate(ordered_ids)
                ],
            )
        return True

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

    def update_dictionary_deck(self, user_id, deck_id, name):
        user_id = self._validate_user_id(user_id)
        name = _validated_notes_text(name, "Название словаря", 100, required=True)
        try:
            deck_id = int(deck_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Словарь не найден") from error
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock, self._connection_factory() as connection:
                cursor = connection.execute(
                    """UPDATE dictionary_decks SET name = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
                    (name, now, deck_id, user_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Словарь не найден")
        except sqlite3.IntegrityError as error:
            raise ValueError("Словарь с таким названием уже существует") from error
        return deck_id

    def delete_dictionary_deck(self, user_id, deck_id):
        user_id = self._validate_user_id(user_id)
        try:
            deck_id = int(deck_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Словарь не найден") from error
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                "DELETE FROM dictionary_decks WHERE id = ? AND user_id = ?",
                (deck_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Словарь не найден")

    def list_dictionary_decks(self, user_id):
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        today = datetime.now().date().isoformat()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT d.id, d.name, COUNT(c.id) AS card_count,
                          SUM(CASE WHEN c.id IS NOT NULL AND
                              (c.next_review = '' OR c.next_review <= ?) THEN 1 ELSE 0 END)
                              AS due_count,
                          SUM(CASE WHEN c.repetitions >= 3 THEN 1 ELSE 0 END)
                              AS mastered_count,
                          (SELECT MAX(r.reviewed_at)
                             FROM dictionary_reviews AS r
                             JOIN dictionary_cards AS reviewed_card
                               ON reviewed_card.id = r.card_id
                            WHERE reviewed_card.deck_id = d.id)
                              AS last_reviewed_at
                   FROM dictionary_decks AS d
                   LEFT JOIN dictionary_cards AS c ON c.deck_id = d.id
                   WHERE d.user_id = ? GROUP BY d.id
                   ORDER BY d.name COLLATE NOCASE""",
                (today, user_id),
            ).fetchall()
        return [
            {"id": int(row["id"]), "name": row["name"],
             "card_count": int(row["card_count"] or 0),
             "due_count": int(row["due_count"] or 0),
             "mastered_count": int(row["mastered_count"] or 0),
             "last_reviewed_at": row["last_reviewed_at"] or ""}
            for row in rows
        ]

    def ensure_demo_dictionary(self, user_id):
        """Создаёт колоду «Политика» и добавляет только отсутствующие демо-карточки."""
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            existing = connection.execute(
                """SELECT id FROM dictionary_decks
                   WHERE user_id = ? AND name = 'Политика' COLLATE NOCASE""",
                (user_id,),
            ).fetchone()
            if existing is None:
                cursor = connection.execute(
                    """INSERT INTO dictionary_decks(
                           user_id, name, created_at, updated_at
                       ) VALUES (?, 'Политика', ?, ?)""",
                    (user_id, now, now),
                )
                deck_id = int(cursor.lastrowid)
            else:
                deck_id = int(existing["id"])
            existing_terms = {
                row["term"] for row in connection.execute(
                    """SELECT term FROM dictionary_cards
                       WHERE user_id = ? AND deck_id = ?""",
                    (user_id, deck_id),
                ).fetchall()
            }
            connection.executemany(
                """INSERT INTO dictionary_cards(
                       deck_id, user_id, term, reading, translation, language,
                       tags, example, example_translation, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 'ja', ?, ?, ?, ?, ?)""",
                (
                    (deck_id, user_id, term, reading, translation, tag,
                     example, example_translation, now, now)
                    for term, reading, translation, tag, example,
                    example_translation in POLITICS_DEMO_CARDS
                    if term not in existing_terms
                ),
            )
            connection.execute(
                """INSERT INTO dictionary_examples(
                       card_id, sort_order, example_text, translation
                   )
                   SELECT c.id, 0, c.example, c.example_translation
                   FROM dictionary_cards AS c
                   WHERE c.user_id = ? AND c.deck_id = ?
                     AND (TRIM(c.example) != '' OR TRIM(c.example_translation) != '')
                     AND NOT EXISTS (
                         SELECT 1 FROM dictionary_examples AS e
                         WHERE e.card_id = c.id
                     )""",
                (user_id, deck_id),
            )
            connection.execute(
                """UPDATE dictionary_cards
                   SET example = '', example_translation = ''
                   WHERE user_id = ? AND deck_id = ?
                     AND id IN (SELECT card_id FROM dictionary_examples)""",
                (user_id, deck_id),
            )
        return deck_id

    def save_dictionary_card(self, user_id, deck_id, term, reading, translation,
                             card_id=None, **card_fields):
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
        language = _validated_notes_text(
            card_fields.get("language", "ja"), "Язык", 20
        ) or "ja"
        tags = _validated_notes_text(card_fields.get("tags"), "Теги", 500)
        raw_examples = card_fields.get("examples")
        if raw_examples is None and (
            card_fields.get("example") or card_fields.get("example_translation")
        ):
            raw_examples = [{
                "text": card_fields.get("example"),
                "translation": card_fields.get("example_translation"),
            }]
        examples = _validated_dictionary_examples(raw_examples)
        notes = _validated_notes_text(
            card_fields.get("notes"), "Заметка", 5000
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            if connection.execute(
                "SELECT 1 FROM dictionary_decks WHERE id = ? AND user_id = ?",
                (deck_id, user_id),
            ).fetchone() is None:
                raise ValueError("Словарь не найден")
            if card_id:
                try:
                    card_id = int(card_id)
                except (TypeError, ValueError) as error:
                    raise ValueError("Карточка не найдена") from error
                cursor = connection.execute(
                    """UPDATE dictionary_cards SET deck_id = ?, term = ?, reading = ?,
                           translation = ?, language = ?, tags = ?, example = '',
                           example_translation = '', notes = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
                    (deck_id, term, reading, translation, language, tags, notes,
                     now, card_id, user_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Карточка не найдена")
            else:
                cursor = connection.execute(
                    """INSERT INTO dictionary_cards(
                           deck_id, user_id, term, reading, translation, language,
                           tags, notes, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (deck_id, user_id, term, reading, translation, language, tags,
                     notes, now, now),
                )
                card_id = int(cursor.lastrowid)
            _replace_dictionary_examples(connection, card_id, examples)
            connection.execute(
                "UPDATE dictionary_decks SET updated_at = ? WHERE id = ?", (now, deck_id)
            )
        return int(card_id)

    def import_dictionary_cards(self, user_id, deck_id, cards):
        """Atomically imports validated cards and skips exact term/reading pairs."""
        user_id = self._validate_user_id(user_id)
        try:
            deck_id = int(deck_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Словарь не найден") from error
        if not isinstance(cards, list) or not cards:
            raise ValueError("В JSON нет карточек для импорта")
        if len(cards) > 200:
            raise ValueError("За один раз можно импортировать не больше 200 карточек")

        prepared = []
        package_keys = set()
        skipped_in_file = 0
        for index, card in enumerate(cards, start=1):
            if not isinstance(card, dict):
                raise ValueError(f"Карточка {index}: ожидался объект")
            try:
                term = _validated_notes_text(
                    card.get("term"), "Слово", 200, required=True
                )
                reading = _validated_notes_text(
                    card.get("reading"), "Чтение", 300
                )
                translation = _validated_notes_text(
                    card.get("translation"), "Перевод", 1000, required=True
                )
                language = _validated_notes_text(
                    card.get("language", "ja"), "Язык", 20
                ) or "ja"
                tags = card.get("tags", "")
                if isinstance(tags, list):
                    tags = ", ".join(str(tag).strip() for tag in tags if str(tag).strip())
                tags = _validated_notes_text(tags, "Теги", 500)
                raw_examples = card.get("examples")
                if raw_examples is None and (
                    card.get("example") or card.get("example_translation")
                ):
                    raw_examples = [{
                        "text": card.get("example"),
                        "translation": card.get("example_translation"),
                    }]
                examples = _validated_dictionary_examples(raw_examples)
                notes = _validated_notes_text(card.get("notes"), "Заметка", 5000)
                source = _validated_notes_text(card.get("source"), "Источник", 1000)
            except ValueError as error:
                raise ValueError(f"Карточка {index}: {error}") from error

            key = (term.casefold(), reading.casefold())
            if key in package_keys:
                skipped_in_file += 1
                continue
            package_keys.add(key)
            prepared.append((
                term, reading, translation, language, tags, notes, source,
                examples,
            ))

        now = datetime.now().isoformat(timespec="seconds")
        added_ids = []
        skipped_existing = 0
        with self._lock, self._connection_factory() as connection:
            if connection.execute(
                "SELECT 1 FROM dictionary_decks WHERE id = ? AND user_id = ?",
                (deck_id, user_id),
            ).fetchone() is None:
                raise ValueError("Словарь не найден")
            existing_keys = {
                (row["term"].casefold(), row["reading"].casefold())
                for row in connection.execute(
                    """SELECT term, reading FROM dictionary_cards
                       WHERE deck_id = ? AND user_id = ?""",
                    (deck_id, user_id),
                ).fetchall()
            }
            for card in prepared:
                key = (card[0].casefold(), card[1].casefold())
                if key in existing_keys:
                    skipped_existing += 1
                    continue
                cursor = connection.execute(
                    """INSERT INTO dictionary_cards(
                           deck_id, user_id, term, reading, translation, language,
                           tags, notes, source, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (deck_id, user_id, *card[:-1], now, now),
                )
                card_id = int(cursor.lastrowid)
                _replace_dictionary_examples(connection, card_id, card[-1])
                added_ids.append(card_id)
                existing_keys.add(key)
            if added_ids:
                connection.execute(
                    "UPDATE dictionary_decks SET updated_at = ? WHERE id = ?",
                    (now, deck_id),
                )
        return {
            "added": len(added_ids),
            "skipped": skipped_in_file + skipped_existing,
            "card_ids": added_ids,
        }

    def list_dictionary_cards(self, user_id, deck_id, due_only=False):
        user_id = self._validate_user_id(user_id)
        try:
            deck_id = int(deck_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Словарь не найден") from error
        today = datetime.now().date().isoformat()
        self._initialize_database()
        query = """SELECT c.id, c.deck_id, c.term, c.reading, c.translation,
                          c.language, c.tags, c.example, c.example_translation,
                          c.notes, c.source, c.is_favorite, c.mistake_count,
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
            card_ids = [int(row["id"]) for row in rows]
            examples_by_card = {}
            if card_ids:
                placeholders = ",".join("?" for _ in card_ids)
                example_rows = connection.execute(
                    f"""SELECT card_id, example_text, translation
                        FROM dictionary_examples
                        WHERE card_id IN ({placeholders})
                        ORDER BY card_id, sort_order, id""",
                    card_ids,
                ).fetchall()
                for example_row in example_rows:
                    examples_by_card.setdefault(int(example_row["card_id"]), []).append({
                        "text": example_row["example_text"],
                        "translation": example_row["translation"],
                    })
        result = []
        for row in rows:
            item = dict(row)
            item["examples"] = examples_by_card.get(int(item["id"]), [])
            first_example = item["examples"][0] if item["examples"] else None
            item["example"] = first_example["text"] if first_example else ""
            item["example_translation"] = (
                first_example["translation"] if first_example else ""
            )
            result.append(item)
        return result

    def delete_dictionary_card(self, user_id, card_id):
        user_id = self._validate_user_id(user_id)
        try:
            card_id = int(card_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Карточка не найдена") from error
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                "DELETE FROM dictionary_cards WHERE id = ? AND user_id = ?",
                (card_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Карточка не найдена")

    def set_dictionary_card_favorite(self, user_id, card_id, is_favorite):
        user_id = self._validate_user_id(user_id)
        try:
            card_id = int(card_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Карточка не найдена") from error
        favorite = 1 if str(is_favorite or "").casefold() in {
            "1", "true", "yes", "on"
        } else 0
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                """UPDATE dictionary_cards SET is_favorite = ?
                   WHERE id = ? AND user_id = ?""",
                (favorite, card_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Карточка не найдена")

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
            mistake_increment = 1 if rating in {"again", "hard"} else 0
            connection.execute(
                """UPDATE dictionary_cards SET repetitions = ?, interval_days = ?,
                       next_review = ?, mistake_count = mistake_count + ?, updated_at = ?
                   WHERE id = ? AND user_id = ?""",
                (repetitions, interval_days, next_review,
                 mistake_increment, datetime.now().isoformat(timespec="seconds"),
                 card_id, user_id),
            )
            connection.execute(
                """INSERT INTO dictionary_reviews(
                       user_id, card_id, rating, reviewed_at
                   ) VALUES (?, ?, ?, ?)""",
                (user_id, card_id, rating,
                 datetime.now().isoformat(timespec="seconds")),
            )
        return {"id": card_id, "interval_days": interval_days,
                "next_review": next_review}

    def dictionary_review_activity(self, user_id, days=7):
        user_id = self._validate_user_id(user_id)
        days = max(1, min(int(days), 31))
        self._initialize_database()
        date_from = (datetime.now().date() - timedelta(days=days - 1)).isoformat()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT substr(reviewed_at, 1, 10) AS review_date,
                          COUNT(*) AS review_count,
                          SUM(CASE WHEN rating IN ('good', 'easy')
                              THEN 1 ELSE 0 END) AS correct_count
                   FROM dictionary_reviews
                   WHERE user_id = ? AND reviewed_at >= ?
                   GROUP BY substr(reviewed_at, 1, 10)""",
                (user_id, date_from),
            ).fetchall()
        return {
            row["review_date"]: {
                "count": int(row["review_count"] or 0),
                "correct": int(row["correct_count"] or 0),
            }
            for row in rows
        }
