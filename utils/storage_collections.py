"""Коллекции, сохранённые материалы и личные закладки."""

import sqlite3
from datetime import datetime


class CollectionStorage:
    def __init__(
        self, initialize_database, connection_factory, lock,
        normalize_url, validate_user_id,
    ):
        self._initialize_database = initialize_database
        self._connection_factory = connection_factory
        self._lock = lock
        self._normalize_url = normalize_url
        self._validate_user_id = validate_user_id

    def list_bookmark_folders(self, user_id):
        """Возвращает только папки указанного пользователя и число материалов."""
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT f.id, f.name, f.description, f.visibility, f.system_key,
                       f.sort_order, f.created_at, f.updated_at,
                       COUNT(DISTINCT b.id) AS bookmark_count,
                       COUNT(DISTINCT n.id) AS note_count
                FROM bookmark_folders AS f
                LEFT JOIN bookmarks AS b
                  ON b.folder_id = f.id AND b.user_id = f.user_id
                LEFT JOIN collection_notes AS n ON n.folder_id = f.id
                WHERE f.user_id = ?
                GROUP BY f.id
                ORDER BY f.sort_order, f.name COLLATE NOCASE, f.id
                """,
                (user_id,),
            ).fetchall()
        return [
            {
                "id": int(row["id"]),
                "name": row["name"],
                "description": row["description"],
                "visibility": row["visibility"],
                "system_key": row["system_key"],
                "sort_order": int(row["sort_order"]),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "bookmark_count": int(row["bookmark_count"]),
                "note_count": int(row["note_count"]),
            }
            for row in rows
        ]

    def ensure_favorites_folder(self, user_id):
        """Возвращает системную папку избранного и один раз переносит старые сердечки."""
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            row = connection.execute(
                """SELECT id FROM bookmark_folders
                   WHERE user_id = ? AND system_key = 'favorites'""",
                (user_id,),
            ).fetchone()
            if row is None:
                row = connection.execute(
                    """SELECT id FROM bookmark_folders
                       WHERE user_id = ? AND name = ? COLLATE NOCASE""",
                    (user_id, "Моё избранное"),
                ).fetchone()
                if row is not None:
                    connection.execute(
                        """UPDATE bookmark_folders
                           SET system_key = 'favorites', updated_at = ? WHERE id = ?""",
                        (now, row["id"]),
                    )
                else:
                    sort_order = int(
                        connection.execute(
                            """SELECT COALESCE(MIN(sort_order), 0) - 1
                               FROM bookmark_folders WHERE user_id = ?""",
                            (user_id,),
                        ).fetchone()[0]
                    )
                    cursor = connection.execute(
                        """INSERT INTO bookmark_folders(
                               user_id, name, system_key, sort_order, created_at, updated_at
                           ) VALUES (?, 'Моё избранное', 'favorites', ?, ?, ?)""",
                        (user_id, sort_order, now, now),
                    )
                    row = {"id": cursor.lastrowid}
                # До появления системной папки сердечки хранились без папки.
                connection.execute(
                    "UPDATE bookmarks SET folder_id = ? WHERE user_id = ? AND folder_id IS NULL",
                    (row["id"], user_id),
                )
            folder_id = int(row["id"])
        return next(
            item for item in self.list_bookmark_folders(user_id) if item["id"] == folder_id
        )

    def create_bookmark_folder(self, user_id, name):
        """Создаёт личную папку с уникальным для пользователя названием."""
        user_id = self._validate_user_id(user_id)
        name = self._validated_folder_name(name)
        self._initialize_database()
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock, self._connection_factory() as connection:
                sort_order = int(
                    connection.execute(
                        """SELECT COALESCE(MAX(sort_order), -1) + 1
                           FROM bookmark_folders WHERE user_id = ?""",
                        (user_id,),
                    ).fetchone()[0]
                )
                cursor = connection.execute(
                    """INSERT INTO bookmark_folders(
                           user_id, name, sort_order, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, ?)""",
                    (user_id, name, sort_order, now, now),
                )
                folder_id = cursor.lastrowid
        except sqlite3.IntegrityError as error:
            raise ValueError("Папка с таким названием уже существует") from error
        return next(
            folder for folder in self.list_bookmark_folders(user_id)
            if folder["id"] == folder_id
        )

    def rename_bookmark_folder(self, user_id, folder_id, name):
        """Переименовывает только принадлежащую пользователю папку."""
        user_id = self._validate_user_id(user_id)
        folder_id = self._validated_folder_id(folder_id)
        name = self._validated_folder_name(name)
        self._initialize_database()
        try:
            with self._lock, self._connection_factory() as connection:
                cursor = connection.execute(
                    """UPDATE bookmark_folders SET name = ?
                       WHERE id = ? AND user_id = ? AND system_key = ''""",
                    (name, folder_id, user_id),
                )
                if cursor.rowcount != 1:
                    raise ValueError("Папка не найдена")
        except sqlite3.IntegrityError as error:
            raise ValueError("Папка с таким названием уже существует") from error
        return next(
            folder for folder in self.list_bookmark_folders(user_id)
            if folder["id"] == folder_id
        )

    def delete_bookmark_folder(self, user_id, folder_id):
        """Удаляет папку; её закладки остаются в разделе «Без папки»."""
        user_id = self._validate_user_id(user_id)
        folder_id = self._validated_folder_id(folder_id)
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                """DELETE FROM bookmark_folders
                   WHERE id = ? AND user_id = ? AND system_key = ''""",
                (folder_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Папка не найдена")

    def save_bookmark_folder_order(self, user_id, folder_ids):
        """Сохраняет полный личный порядок подборок после перетаскивания."""
        user_id = self._validate_user_id(user_id)
        if not isinstance(folder_ids, list):
            raise ValueError("Некорректный порядок подборок")
        requested = []
        for value in folder_ids:
            try:
                folder_id = int(value)
            except (TypeError, ValueError) as error:
                raise ValueError("Некорректный порядок подборок") from error
            if folder_id < 1 or folder_id in requested:
                raise ValueError("Некорректный порядок подборок")
            requested.append(folder_id)
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
            owned = {
                int(row["id"]) for row in connection.execute(
                    "SELECT id FROM bookmark_folders WHERE user_id = ?",
                    (user_id,),
                ).fetchall()
            }
            if set(requested) != owned:
                raise ValueError("Список подборок изменился. Обнови страницу")
            connection.executemany(
                "UPDATE bookmark_folders SET sort_order = ? WHERE id = ? AND user_id = ?",
                [(position, folder_id, user_id) for position, folder_id in enumerate(requested)],
            )
        return self.list_bookmark_folders(user_id)

    def update_collection(self, user_id, folder_id, name, description="", visibility="private",
                          shared_user_ids=None):
        """Обновляет подборку и её наследуемый доступ только от имени владельца."""
        user_id = self._validate_user_id(user_id)
        folder_id = self._owned_folder_id(user_id, folder_id)
        name = self._validated_folder_name(name)
        description = str(description or "").strip()
        if len(description) > 1000:
            raise ValueError("Описание не должно превышать 1000 символов")
        visibility = str(visibility or "private").strip().casefold()
        if visibility not in {"private", "all", "selected"}:
            raise ValueError("Неизвестный режим доступа")
        requested_ids = set()
        for value in shared_user_ids or []:
            shared_id = self._validate_user_id(value)
            if shared_id != user_id:
                requested_ids.add(shared_id)
        now = datetime.now().isoformat(timespec="seconds")
        try:
            with self._lock, self._connection_factory() as connection:
                system_row = connection.execute(
                    "SELECT system_key, name FROM bookmark_folders WHERE id = ?",
                    (folder_id,),
                ).fetchone()
                if system_row["system_key"]:
                    name = system_row["name"]
                connection.execute(
                    """UPDATE bookmark_folders
                       SET name = ?, description = ?, visibility = ?, updated_at = ?
                       WHERE id = ? AND user_id = ?""",
                    (name, description, visibility, now, folder_id, user_id),
                )
                connection.execute(
                    "DELETE FROM bookmark_folder_shares WHERE folder_id = ?",
                    (folder_id,),
                )
                if visibility == "selected":
                    connection.executemany(
                        """INSERT INTO bookmark_folder_shares(folder_id, user_id, created_at)
                           VALUES (?, ?, ?)""",
                        [(folder_id, shared_id, now) for shared_id in sorted(requested_ids)],
                    )
        except sqlite3.IntegrityError as error:
            raise ValueError("Подборка с таким названием уже существует") from error
        return self.load_collection(user_id, folder_id)

    def load_collection(self, user_id, folder_id):
        """Возвращает доступную подборку и отмечает права текущего пользователя."""
        user_id = self._validate_user_id(user_id)
        folder_id = self._validated_folder_id(folder_id)
        self._initialize_database()
        with self._connection_factory() as connection:
            row = connection.execute(
                """SELECT f.*, u.username AS owner_name,
                          CASE WHEN f.user_id = ? THEN 1 ELSE 0 END AS can_edit
                   FROM bookmark_folders AS f
                   JOIN users AS u ON u.id = f.user_id
                   WHERE f.id = ? AND (
                       f.user_id = ? OR f.visibility = 'all' OR EXISTS(
                           SELECT 1 FROM bookmark_folder_shares AS s
                           WHERE s.folder_id = f.id AND s.user_id = ?
                       )
                   )""",
                (user_id, folder_id, user_id, user_id),
            ).fetchone()
            if row is None:
                return None
            shared_rows = connection.execute(
                """SELECT u.id, u.username FROM bookmark_folder_shares AS s
                   JOIN users AS u ON u.id = s.user_id
                   WHERE s.folder_id = ? ORDER BY u.username COLLATE NOCASE""",
                (folder_id,),
            ).fetchall()
        return {
            "id": int(row["id"]), "user_id": int(row["user_id"]),
            "name": row["name"], "description": row["description"],
            "visibility": row["visibility"], "owner_name": row["owner_name"],
            "sort_order": int(row["sort_order"]),
            "system_key": row["system_key"],
            "can_edit": bool(row["can_edit"]),
            "shared_users": [dict(id=int(item["id"]), username=item["username"])
                             for item in shared_rows],
        }

    def list_shared_collections(self, user_id):
        """Показывает подборки других владельцев, доступные пользователю."""
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT f.id, f.name, f.description, f.visibility,
                          u.username AS owner_name,
                          COUNT(DISTINCT b.id) AS bookmark_count,
                          COUNT(DISTINCT n.id) AS note_count
                   FROM bookmark_folders AS f
                   JOIN users AS u ON u.id = f.user_id
                   LEFT JOIN bookmarks AS b ON b.folder_id = f.id
                   LEFT JOIN collection_notes AS n ON n.folder_id = f.id
                   WHERE f.user_id != ? AND (f.visibility = 'all' OR EXISTS(
                       SELECT 1 FROM bookmark_folder_shares AS s
                       WHERE s.folder_id = f.id AND s.user_id = ?
                   ))
                   GROUP BY f.id ORDER BY f.sort_order, f.name COLLATE NOCASE, f.id""",
                (user_id, user_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_collection_bookmarks(self, user_id, folder_id):
        collection = self.load_collection(user_id, folder_id)
        if collection is None:
            raise ValueError("Подборка не найдена")
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT b.*, f.name AS folder_name FROM bookmarks AS b
                   JOIN bookmark_folders AS f ON f.id = b.folder_id
                   WHERE b.folder_id = ? ORDER BY b.updated_at DESC, b.id DESC""",
                (collection["id"],),
            ).fetchall()
        return [self._bookmark_from_row(row) for row in rows]

    def save_external_bookmark(self, user_id, folder_id, url, title, note=""):
        """Добавляет в собственную подборку ссылку, которой нет в ленте."""
        normalized = self._normalize_url(str(url or "").strip())
        if not normalized.startswith(("http://", "https://")):
            raise ValueError("Укажи полный адрес, начинающийся с http:// или https://")
        title = " ".join(str(title or "").split())[:1000]
        if not title:
            raise ValueError("Укажи название материала")
        return self.save_bookmark(
            user_id,
            {"url": normalized, "title": title, "source": "Внешний источник", "date": ""},
            folder_id,
            note,
        )

    def _validated_collection_note_fields(self, title, body, url="", source="",
                                          publication_date="", comment=""):
        """Проверяет и нормализует редактируемые поля заметки."""
        title = " ".join(str(title or "").split())
        body = str(body or "").strip()
        raw_url = str(url or "").strip()
        normalized_url = self._normalize_url(raw_url) if raw_url else ""
        if raw_url and not normalized_url.startswith(("http://", "https://")):
            raise ValueError("Укажи полный адрес, начинающийся с http:// или https://")
        source = " ".join(str(source or "").split())
        if len(source) > 300:
            raise ValueError("Источник не должен превышать 300 символов")
        publication_date = str(publication_date or "").strip()
        if publication_date:
            try:
                datetime.strptime(publication_date, "%Y-%m-%d")
            except ValueError as error:
                raise ValueError("Дата публикации указана неверно") from error
        comment = self._validated_bookmark_note(comment)
        if not 1 <= len(title) <= 200:
            raise ValueError("Заголовок заметки должен содержать от 1 до 200 символов")
        if len(body) > 20_000:
            raise ValueError("Текст заметки не должен превышать 20000 символов")
        return title, body, normalized_url, source, publication_date, comment

    def save_collection_note(self, user_id, folder_id, title, body, url="", source="",
                             publication_date="", comment=""):
        """Добавляет в подборку заметку или вручную сохранённую статью."""
        user_id = self._validate_user_id(user_id)
        folder_id = self._owned_folder_id(user_id, folder_id)
        fields = self._validated_collection_note_fields(
            title, body, url, source, publication_date, comment,
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                """INSERT INTO collection_notes(
                       folder_id, user_id, title, body, url, source,
                       publication_date, comment, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (folder_id, user_id, *fields, now, now),
            )
        return cursor.lastrowid

    def update_collection_note(self, user_id, folder_id, note_id, title, body, url="",
                               source="", publication_date="", comment=""):
        """Обновляет существующую заметку владельца без создания дубликата."""
        user_id = self._validate_user_id(user_id)
        folder_id = self._owned_folder_id(user_id, folder_id)
        try:
            note_id = int(note_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Заметка не найдена") from error
        fields = self._validated_collection_note_fields(
            title, body, url, source, publication_date, comment,
        )
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                """UPDATE collection_notes
                   SET title = ?, body = ?, url = ?, source = ?,
                       publication_date = ?, comment = ?, updated_at = ?
                   WHERE id = ? AND folder_id = ? AND user_id = ?""",
                (*fields, now, note_id, folder_id, user_id),
            )
        if cursor.rowcount != 1:
            raise ValueError("Заметка не найдена")
        return note_id

    def list_collection_notes(self, user_id, folder_id):
        collection = self.load_collection(user_id, folder_id)
        if collection is None:
            raise ValueError("Подборка не найдена")
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT id, title, body, url, source, publication_date, comment,
                          created_at, updated_at
                   FROM collection_notes WHERE folder_id = ?
                   ORDER BY updated_at DESC, id DESC""",
                (collection["id"],),
            ).fetchall()
        return [dict(row) for row in rows]

    def list_collection_note_read_ids(self, user_id, folder_id):
        """Возвращает статьи подборки, прочитанные именно этим пользователем."""
        user_id = self._validate_user_id(user_id)
        collection = self.load_collection(user_id, folder_id)
        if collection is None:
            raise ValueError("Подборка не найдена")
        with self._connection_factory() as connection:
            rows = connection.execute(
                """SELECT r.note_id FROM collection_note_reads AS r
                   JOIN collection_notes AS n ON n.id = r.note_id
                   WHERE r.user_id = ? AND n.folder_id = ?""",
                (user_id, collection["id"]),
            ).fetchall()
        return {int(row["note_id"]) for row in rows}

    def set_collection_note_read(self, user_id, folder_id, note_id, is_read):
        """Меняет личную отметку чтения, не затрагивая других читателей."""
        user_id = self._validate_user_id(user_id)
        collection = self.load_collection(user_id, folder_id)
        if collection is None:
            raise ValueError("Подборка не найдена")
        try:
            note_id = int(note_id)
        except (TypeError, ValueError) as error:
            raise ValueError("Статья не найдена") from error
        with self._lock, self._connection_factory() as connection:
            note = connection.execute(
                "SELECT id FROM collection_notes WHERE id = ? AND folder_id = ?",
                (note_id, collection["id"]),
            ).fetchone()
            if note is None:
                raise ValueError("Статья не найдена")
            if is_read:
                connection.execute(
                    """INSERT INTO collection_note_reads(user_id, note_id, read_at)
                       VALUES (?, ?, ?)
                       ON CONFLICT(user_id, note_id)
                       DO UPDATE SET read_at = excluded.read_at""",
                    (user_id, note_id, datetime.now().isoformat(timespec="seconds")),
                )
            else:
                connection.execute(
                    "DELETE FROM collection_note_reads WHERE user_id = ? AND note_id = ?",
                    (user_id, note_id),
                )
        return bool(is_read)

    def delete_collection_note(self, user_id, folder_id, note_id):
        user_id = self._validate_user_id(user_id)
        folder_id = self._owned_folder_id(user_id, folder_id)
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                """DELETE FROM collection_notes
                   WHERE id = ? AND folder_id = ? AND user_id = ?""",
                (int(note_id), folder_id, user_id),
            )
        if cursor.rowcount != 1:
            raise ValueError("Заметка не найдена")

    def save_bookmark(self, user_id, item, folder_id=None, note=""):
        """Сохраняет снимок новости в личных закладках пользователя."""
        user_id = self._validate_user_id(user_id)
        if not isinstance(item, dict):
            raise ValueError("Новость не найдена")
        normalized = self._normalize_url(item.get("url", ""))
        title = " ".join(str(item.get("title", "")).split())[:1000]
        if not normalized or not title:
            raise ValueError("Новость не найдена")
        folder_id = self._owned_folder_id(user_id, folder_id)
        note = self._validated_bookmark_note(note)
        now = datetime.now().isoformat(timespec="seconds")
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
            connection.execute(
                """
                INSERT INTO bookmarks(
                    user_id, folder_id, normalized_url, url, source, title,
                    publication_date, note, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, normalized_url) DO UPDATE SET
                    folder_id = COALESCE(excluded.folder_id, bookmarks.folder_id),
                    url = excluded.url,
                    source = excluded.source,
                    title = excluded.title,
                    publication_date = excluded.publication_date,
                    note = CASE WHEN excluded.note != '' THEN excluded.note ELSE bookmarks.note END,
                    updated_at = excluded.updated_at
                """,
                (
                    user_id,
                    folder_id,
                    normalized,
                    item.get("url", ""),
                    str(item.get("source", ""))[:300],
                    title,
                    str(item.get("date", ""))[:50],
                    note,
                    now,
                    now,
                ),
            )
        return self.load_bookmark(user_id, normalized)

    def update_bookmark(self, user_id, url, folder_id=None, note=""):
        """Перемещает личную закладку и сохраняет заметку пользователя."""
        user_id = self._validate_user_id(user_id)
        normalized = self._normalize_url(url)
        folder_id = self._owned_folder_id(user_id, folder_id)
        note = self._validated_bookmark_note(note)
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                """
                UPDATE bookmarks
                SET folder_id = ?, note = ?, updated_at = ?
                WHERE user_id = ? AND normalized_url = ?
                """,
                (
                    folder_id,
                    note,
                    datetime.now().isoformat(timespec="seconds"),
                    user_id,
                    normalized,
                ),
            )
            if cursor.rowcount != 1:
                raise ValueError("Закладка не найдена")
        return self.load_bookmark(user_id, normalized)

    def remove_bookmark(self, user_id, url):
        """Удаляет одну личную закладку, не затрагивая новость в общей базе."""
        user_id = self._validate_user_id(user_id)
        normalized = self._normalize_url(url)
        self._initialize_database()
        with self._lock, self._connection_factory() as connection:
            cursor = connection.execute(
                "DELETE FROM bookmarks WHERE user_id = ? AND normalized_url = ?",
                (user_id, normalized),
            )
        return cursor.rowcount == 1

    def load_bookmark(self, user_id, url):
        user_id = self._validate_user_id(user_id)
        normalized = self._normalize_url(url)
        self._initialize_database()
        with self._connection_factory() as connection:
            row = connection.execute(
                """
                SELECT b.*, f.name AS folder_name
                FROM bookmarks AS b
                LEFT JOIN bookmark_folders AS f
                  ON f.id = b.folder_id AND f.user_id = b.user_id
                WHERE b.user_id = ? AND b.normalized_url = ?
                """,
                (user_id, normalized),
            ).fetchone()
        return self._bookmark_from_row(row)

    def list_bookmarks(self, user_id, folder_id="all"):
        """Возвращает личные закладки, при необходимости фильтруя по папке."""
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        parameters = [user_id]
        condition = ""
        if folder_id == "unfiled":
            condition = " AND b.folder_id IS NULL"
        elif folder_id not in {"all", None, ""}:
            owned_id = self._owned_folder_id(user_id, folder_id)
            condition = " AND b.folder_id = ?"
            parameters.append(owned_id)
        with self._connection_factory() as connection:
            rows = connection.execute(
                """
                SELECT b.*, f.name AS folder_name
                FROM bookmarks AS b
                LEFT JOIN bookmark_folders AS f
                  ON f.id = b.folder_id AND f.user_id = b.user_id
                WHERE b.user_id = ?
                """ + condition + " ORDER BY b.updated_at DESC, b.id DESC",
                parameters,
            ).fetchall()
        return [self._bookmark_from_row(row) for row in rows]

    def bookmarked_urls(self, user_id):
        """Возвращает URL личных закладок для подсветки сердечек в ленте."""
        return [item["url"] for item in self.list_bookmarks(user_id)]

    def count_bookmarks(self, user_id):
        user_id = self._validate_user_id(user_id)
        self._initialize_database()
        with self._connection_factory() as connection:
            return int(
                connection.execute(
                    "SELECT COUNT(*) FROM bookmarks WHERE user_id = ?",
                    (user_id,),
                ).fetchone()[0]
            )

    def _validated_folder_id(self, value):
        try:
            folder_id = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError("Папка не найдена") from error
        if folder_id < 1:
            raise ValueError("Папка не найдена")
        return folder_id

    def _owned_folder_id(self, user_id, value):
        if value in {None, "", "unfiled"}:
            return None
        folder_id = self._validated_folder_id(value)
        self._initialize_database()
        with self._connection_factory() as connection:
            exists = connection.execute(
                "SELECT 1 FROM bookmark_folders WHERE id = ? AND user_id = ?",
                (folder_id, user_id),
            ).fetchone()
        if exists is None:
            raise ValueError("Папка не найдена")
        return folder_id

    def _validated_folder_name(self, value):
        name = " ".join(str(value or "").split())
        if not 1 <= len(name) <= 80:
            raise ValueError("Название папки должно содержать от 1 до 80 символов")
        return name

    def _validated_bookmark_note(self, value):
        note = str(value or "").strip()
        if len(note) > 5000:
            raise ValueError("Заметка не должна превышать 5000 символов")
        return note

    def _bookmark_from_row(self, row):
        if row is None:
            return None
        return {
            "id": int(row["id"]),
            "folder_id": int(row["folder_id"]) if row["folder_id"] else None,
            "folder_name": row["folder_name"] or "",
            "normalized_url": row["normalized_url"],
            "url": row["url"],
            "source": row["source"],
            "title": row["title"],
            "date": row["publication_date"],
            "note": row["note"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
