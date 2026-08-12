"""SQLite-хранилище новостей и безопасные JSON-помощники."""

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from threading import RLock

from werkzeug.security import check_password_hash, generate_password_hash

from utils.logger import get_logger
from utils.news import deduplicate_news, merge_news, normalize_url


PROJECT_DIR = Path(__file__).resolve().parent.parent
ALL_NEWS_FILE = PROJECT_DIR / "all_news.json"
FOUND_NEWS_FILE = PROJECT_DIR / "found_news.json"
DATABASE_FILE = Path(
    os.environ.get("NEWS_DATABASE_PATH", PROJECT_DIR / "news.db")
)
BACKUP_DIR = Path(
    os.environ.get("NEWS_BACKUP_DIR", PROJECT_DIR / "backups")
)
logger = get_logger("storage")
STORAGE_LOCK = RLock()
JSON_MIGRATION_KEY = "json_migration_v1"
MAX_CACHED_ARTICLE_CHARS = 100_000
_INITIALIZED_DATABASES = set()
_INITIALIZATION_RESULTS = {}


def _load_json(path):
    """Читает служебный JSON. Оставлен для настроек, статуса и миграции."""
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, list):
            raise ValueError("ожидался JSON-массив")
        return data
    except (OSError, json.JSONDecodeError, ValueError) as error:
        logger.error(f"Не удалось прочитать {path.name}: {error}")
        return []


def _write_json_atomic(path, data):
    """Записывает небольшой JSON через временный файл без риска обрыва."""
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
            temp_name = file.name
        os.replace(temp_name, path)
    finally:
        if temp_name and os.path.exists(temp_name):
            os.unlink(temp_name)


def _connect():
    """Создаёт отдельное SQLite-соединение для текущей операции."""
    DATABASE_FILE.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_FILE, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _create_schema(connection):
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA synchronous = NORMAL")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS news_items (
            news_key TEXT PRIMARY KEY,
            normalized_url TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            publication_date TEXT NOT NULL DEFAULT '',
            parsed_date TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS found_items (
            news_key TEXT PRIMARY KEY,
            payload_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(news_key) REFERENCES news_items(news_key)
                ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS article_cache (
            normalized_url TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL DEFAULT '',
            paragraphs_json TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'user'
                CHECK(role IN ('admin', 'user')),
            is_active INTEGER NOT NULL DEFAULT 1
                CHECK(is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            last_login_at TEXT NOT NULL DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS bookmark_folders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL COLLATE NOCASE,
            created_at TEXT NOT NULL,
            UNIQUE(user_id, name),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bookmarks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            folder_id INTEGER,
            normalized_url TEXT NOT NULL,
            url TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            publication_date TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(user_id, normalized_url),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(folder_id) REFERENCES bookmark_folders(id)
                ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS user_source_orders (
            user_id INTEGER NOT NULL,
            source_group TEXT NOT NULL,
            source_order_json TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, source_group),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_news_source
            ON news_items(source);
        CREATE INDEX IF NOT EXISTS idx_news_publication_date
            ON news_items(publication_date DESC, parsed_date DESC);
        CREATE INDEX IF NOT EXISTS idx_news_normalized_url
            ON news_items(normalized_url);
        CREATE INDEX IF NOT EXISTS idx_users_role
            ON users(role, is_active);
        CREATE INDEX IF NOT EXISTS idx_bookmark_folders_user
            ON bookmark_folders(user_id, name);
        CREATE INDEX IF NOT EXISTS idx_bookmarks_user
            ON bookmarks(user_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_bookmarks_folder
            ON bookmarks(user_id, folder_id, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_user_source_orders_user
            ON user_source_orders(user_id, source_group);
        """
    )


def count_users():
    """Возвращает число учётных записей, включая отключённые."""
    initialize_database()
    with _connect() as connection:
        return int(connection.execute("SELECT COUNT(*) FROM users").fetchone()[0])


def create_user(username, password, role="user"):
    """Создаёт пользователя с хешем пароля; открытый пароль не хранится."""
    username = _validate_username(username)
    password = _validate_password(password)
    role = str(role or "user").strip().casefold()
    if role not in {"admin", "user"}:
        raise ValueError("Неизвестная роль пользователя")

    initialize_database()
    created_at = datetime.now().isoformat(timespec="seconds")
    try:
        with STORAGE_LOCK, _connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users(
                    username, password_hash, role, is_active, created_at
                ) VALUES (?, ?, ?, 1, ?)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                    created_at,
                ),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Пользователь с таким именем уже существует") from error
    return load_user(user_id)


def load_user(user_id):
    """Возвращает безопасные поля пользователя без хеша пароля."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return None
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT id, username, role, is_active, created_at, last_login_at
            FROM users WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
    return _user_from_row(row)


def list_users():
    """Возвращает безопасный список пользователей без хешей паролей."""
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT id, username, role, is_active, created_at, last_login_at
            FROM users
            ORDER BY CASE role WHEN 'admin' THEN 0 ELSE 1 END,
                     username COLLATE NOCASE
            """
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def set_user_password(user_id, password):
    """Заменяет пароль пользователя новым защищённым хешем."""
    password = _validate_password(password)
    user = load_user(user_id)
    if user is None:
        raise ValueError("Пользователь не найден")
    with STORAGE_LOCK, _connect() as connection:
        connection.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user["id"]),
        )
    return load_user(user["id"])


def set_user_role(user_id, role):
    """Меняет роль, не позволяя убрать последнего активного администратора."""
    role = str(role or "").strip().casefold()
    if role not in {"admin", "user"}:
        raise ValueError("Неизвестная роль пользователя")
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Пользователь не найден") from error

    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT role, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Пользователь не найден")
        if row["role"] == "admin" and role != "admin" and row["is_active"]:
            active_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError("Нельзя понизить последнего активного администратора")
        connection.execute(
            "UPDATE users SET role = ? WHERE id = ?",
            (role, user_id),
        )
    return load_user(user_id)


def set_user_active(user_id, is_active):
    """Включает или отключает вход, сохраняя все данные пользователя."""
    try:
        user_id = int(user_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Пользователь не найден") from error
    is_active = bool(is_active)

    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            "SELECT role, is_active FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Пользователь не найден")
        if row["role"] == "admin" and row["is_active"] and not is_active:
            active_admins = connection.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
            ).fetchone()[0]
            if active_admins <= 1:
                raise ValueError("Нельзя отключить последнего активного администратора")
        connection.execute(
            "UPDATE users SET is_active = ? WHERE id = ?",
            (int(is_active), user_id),
        )
    return load_user(user_id)


def authenticate_user(username, password):
    """Проверяет пароль и возвращает активного пользователя."""
    username = " ".join(str(username or "").split())
    password = str(password or "")
    if not username or not password:
        return None
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        row = connection.execute(
            """
            SELECT id, username, password_hash, role, is_active,
                   created_at, last_login_at
            FROM users WHERE username = ? COLLATE NOCASE
            """,
            (username,),
        ).fetchone()
        if (
            row is None
            or not bool(row["is_active"])
            or not check_password_hash(row["password_hash"], password)
        ):
            return None
        logged_at = datetime.now().isoformat(timespec="seconds")
        connection.execute(
            "UPDATE users SET last_login_at = ? WHERE id = ?",
            (logged_at, row["id"]),
        )
    user = _user_from_row(row)
    user["last_login_at"] = logged_at
    return user


def load_source_order(user_id, source_group):
    """Возвращает личный порядок источников для одного раздела."""
    user_id = _validated_user_id(user_id)
    source_group = _validated_source_group(source_group)
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT source_order_json
            FROM user_source_orders
            WHERE user_id = ? AND source_group = ?
            """,
            (user_id, source_group),
        ).fetchone()
    if row is None:
        return []
    try:
        values = json.loads(row["source_order_json"])
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    for value in values:
        source = " ".join(str(value or "").split())[:300]
        if source and source.casefold() not in seen:
            seen.add(source.casefold())
            result.append(source)
    return result


def save_source_order(user_id, source_group, sources):
    """Сохраняет личный порядок источников, не затрагивая других пользователей."""
    user_id = _validated_user_id(user_id)
    source_group = _validated_source_group(source_group)
    if not isinstance(sources, list) or len(sources) > 500:
        raise ValueError("Некорректный список источников")
    order = []
    seen = set()
    for value in sources:
        source = " ".join(str(value or "").split())
        key = source.casefold()
        if not source or len(source) > 300 or key in seen:
            continue
        seen.add(key)
        order.append(source)
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO user_source_orders(
                user_id, source_group, source_order_json, updated_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, source_group) DO UPDATE SET
                source_order_json = excluded.source_order_json,
                updated_at = excluded.updated_at
            """,
            (
                user_id,
                source_group,
                json.dumps(order, ensure_ascii=False),
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    return order


def list_bookmark_folders(user_id):
    """Возвращает только папки указанного пользователя и число материалов."""
    user_id = _validated_user_id(user_id)
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT f.id, f.name, f.created_at, COUNT(b.id) AS bookmark_count
            FROM bookmark_folders AS f
            LEFT JOIN bookmarks AS b
              ON b.folder_id = f.id AND b.user_id = f.user_id
            WHERE f.user_id = ?
            GROUP BY f.id, f.name, f.created_at
            ORDER BY f.name COLLATE NOCASE
            """,
            (user_id,),
        ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": row["name"],
            "created_at": row["created_at"],
            "bookmark_count": int(row["bookmark_count"]),
        }
        for row in rows
    ]


def create_bookmark_folder(user_id, name):
    """Создаёт личную папку с уникальным для пользователя названием."""
    user_id = _validated_user_id(user_id)
    name = _validated_folder_name(name)
    initialize_database()
    try:
        with STORAGE_LOCK, _connect() as connection:
            cursor = connection.execute(
                "INSERT INTO bookmark_folders(user_id, name, created_at) VALUES (?, ?, ?)",
                (user_id, name, datetime.now().isoformat(timespec="seconds")),
            )
            folder_id = cursor.lastrowid
    except sqlite3.IntegrityError as error:
        raise ValueError("Папка с таким названием уже существует") from error
    return next(
        folder for folder in list_bookmark_folders(user_id)
        if folder["id"] == folder_id
    )


def rename_bookmark_folder(user_id, folder_id, name):
    """Переименовывает только принадлежащую пользователю папку."""
    user_id = _validated_user_id(user_id)
    folder_id = _validated_folder_id(folder_id)
    name = _validated_folder_name(name)
    initialize_database()
    try:
        with STORAGE_LOCK, _connect() as connection:
            cursor = connection.execute(
                "UPDATE bookmark_folders SET name = ? WHERE id = ? AND user_id = ?",
                (name, folder_id, user_id),
            )
            if cursor.rowcount != 1:
                raise ValueError("Папка не найдена")
    except sqlite3.IntegrityError as error:
        raise ValueError("Папка с таким названием уже существует") from error
    return next(
        folder for folder in list_bookmark_folders(user_id)
        if folder["id"] == folder_id
    )


def delete_bookmark_folder(user_id, folder_id):
    """Удаляет папку; её закладки остаются в разделе «Без папки»."""
    user_id = _validated_user_id(user_id)
    folder_id = _validated_folder_id(folder_id)
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM bookmark_folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        )
        if cursor.rowcount != 1:
            raise ValueError("Папка не найдена")


def save_bookmark(user_id, item, folder_id=None, note=""):
    """Сохраняет снимок новости в личных закладках пользователя."""
    user_id = _validated_user_id(user_id)
    if not isinstance(item, dict):
        raise ValueError("Новость не найдена")
    normalized = normalize_url(item.get("url", ""))
    title = " ".join(str(item.get("title", "")).split())[:1000]
    if not normalized or not title:
        raise ValueError("Новость не найдена")
    folder_id = _owned_folder_id(user_id, folder_id)
    note = _validated_bookmark_note(note)
    now = datetime.now().isoformat(timespec="seconds")
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
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
    return load_bookmark(user_id, normalized)


def update_bookmark(user_id, url, folder_id=None, note=""):
    """Перемещает личную закладку и сохраняет заметку пользователя."""
    user_id = _validated_user_id(user_id)
    normalized = normalize_url(url)
    folder_id = _owned_folder_id(user_id, folder_id)
    note = _validated_bookmark_note(note)
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
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
    return load_bookmark(user_id, normalized)


def remove_bookmark(user_id, url):
    """Удаляет одну личную закладку, не затрагивая новость в общей базе."""
    user_id = _validated_user_id(user_id)
    normalized = normalize_url(url)
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        cursor = connection.execute(
            "DELETE FROM bookmarks WHERE user_id = ? AND normalized_url = ?",
            (user_id, normalized),
        )
    return cursor.rowcount == 1


def load_bookmark(user_id, url):
    user_id = _validated_user_id(user_id)
    normalized = normalize_url(url)
    initialize_database()
    with _connect() as connection:
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
    return _bookmark_from_row(row)


def list_bookmarks(user_id, folder_id="all"):
    """Возвращает личные закладки, при необходимости фильтруя по папке."""
    user_id = _validated_user_id(user_id)
    initialize_database()
    parameters = [user_id]
    condition = ""
    if folder_id == "unfiled":
        condition = " AND b.folder_id IS NULL"
    elif folder_id not in {"all", None, ""}:
        owned_id = _owned_folder_id(user_id, folder_id)
        condition = " AND b.folder_id = ?"
        parameters.append(owned_id)
    with _connect() as connection:
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
    return [_bookmark_from_row(row) for row in rows]


def bookmarked_urls(user_id):
    """Возвращает URL личных закладок для подсветки сердечек в ленте."""
    return [item["url"] for item in list_bookmarks(user_id)]


def count_bookmarks(user_id):
    user_id = _validated_user_id(user_id)
    initialize_database()
    with _connect() as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM bookmarks WHERE user_id = ?",
                (user_id,),
            ).fetchone()[0]
        )


def _validated_user_id(value):
    try:
        user_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Пользователь не найден") from error
    if user_id < 1 or load_user(user_id) is None:
        raise ValueError("Пользователь не найден")
    return user_id


def _validated_source_group(value):
    source_group = str(value or "").strip().casefold()
    if source_group not in {"government", "agencies", "newspapers"}:
        raise ValueError("Неизвестный раздел источников")
    return source_group


def _validated_folder_id(value):
    try:
        folder_id = int(value)
    except (TypeError, ValueError) as error:
        raise ValueError("Папка не найдена") from error
    if folder_id < 1:
        raise ValueError("Папка не найдена")
    return folder_id


def _owned_folder_id(user_id, value):
    if value in {None, "", "unfiled"}:
        return None
    folder_id = _validated_folder_id(value)
    initialize_database()
    with _connect() as connection:
        exists = connection.execute(
            "SELECT 1 FROM bookmark_folders WHERE id = ? AND user_id = ?",
            (folder_id, user_id),
        ).fetchone()
    if exists is None:
        raise ValueError("Папка не найдена")
    return folder_id


def _validated_folder_name(value):
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= 80:
        raise ValueError("Название папки должно содержать от 1 до 80 символов")
    return name


def _validated_bookmark_note(value):
    note = str(value or "").strip()
    if len(note) > 5000:
        raise ValueError("Заметка не должна превышать 5000 символов")
    return note


def _bookmark_from_row(row):
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


def _validate_username(value):
    username = " ".join(str(value or "").split())
    if not 3 <= len(username) <= 50:
        raise ValueError("Логин должен содержать от 3 до 50 символов")
    if not all(character.isalnum() or character in "._-" for character in username):
        raise ValueError("В логине разрешены буквы, цифры, точка, дефис и подчёркивание")
    return username


def _validate_password(value):
    password = str(value or "")
    if not 10 <= len(password) <= 256:
        raise ValueError("Пароль должен содержать не менее 10 символов")
    return password


def _user_from_row(row):
    if row is None:
        return None
    return {
        "id": int(row["id"]),
        "username": row["username"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "created_at": row["created_at"],
        "last_login_at": row["last_login_at"],
    }


def initialize_database():
    """
    Создаёт базу и один раз переносит старые JSON-файлы.

    Исходные JSON не удаляются: они остаются резервным снимком на случай,
    если пользователь захочет проверить миграцию или откатиться.
    """
    database_id = str(DATABASE_FILE.resolve())
    with STORAGE_LOCK:
        if database_id in _INITIALIZED_DATABASES and DATABASE_FILE.exists():
            return dict(_INITIALIZATION_RESULTS[database_id])

        with _connect() as connection:
            _create_schema(connection)
            completed = connection.execute(
                "SELECT 1 FROM metadata WHERE key = ?",
                (JSON_MIGRATION_KEY,),
            ).fetchone()
            if completed:
                stats = database_stats(connection=connection)
                _INITIALIZED_DATABASES.add(database_id)
                _INITIALIZATION_RESULTS[database_id] = dict(stats)
                return stats

            # Блокирует только конкурирующую первую миграцию. Обычные чтения
            # продолжают работать благодаря WAL, а второй процесс дождётся
            # завершения и повторно проверит metadata.
            connection.execute("BEGIN IMMEDIATE")
            completed = connection.execute(
                "SELECT 1 FROM metadata WHERE key = ?",
                (JSON_MIGRATION_KEY,),
            ).fetchone()
            if completed:
                stats = database_stats(connection=connection)
                _INITIALIZED_DATABASES.add(database_id)
                _INITIALIZATION_RESULTS[database_id] = dict(stats)
                return stats

            all_news = deduplicate_news(_load_json(ALL_NEWS_FILE))
            found_news = deduplicate_news(_load_json(FOUND_NEWS_FILE))
            if all_news or found_news:
                # Гарантируем, что каждая найденная запись существует в
                # news_items, но не переносим поле keywords в общую ленту.
                available = {_news_key(item) for item in all_news}
                missing = []
                for item in found_news:
                    if _news_key(item) in available:
                        continue
                    clean_item = dict(item)
                    clean_item.pop("keywords", None)
                    missing.append(clean_item)
                all_news = [*all_news, *missing]
                _replace_collections(
                    connection,
                    all_news,
                    found_news,
                )
                logger.info(
                    "Миграция JSON → SQLite завершена: "
                    f"{len(all_news)} новостей, {len(found_news)} совпадений"
                )

            connection.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
                (
                    JSON_MIGRATION_KEY,
                    json.dumps(
                        {
                            "completed_at": datetime.now().isoformat(timespec="seconds"),
                            "all_news": len(all_news),
                            "found_news": len(found_news),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
            stats = database_stats(connection=connection)
            _INITIALIZED_DATABASES.add(database_id)
            _INITIALIZATION_RESULTS[database_id] = dict(stats)
            return stats


def load_all_news():
    initialize_database()
    with _connect() as connection:
        # Правила очистки развиваются вместе с парсерами. Применяем их и к
        # уже накопленной SQLite-базе, чтобы старые служебные карточки не
        # оставались в интерфейсе до следующего запуска своего источника.
        return deduplicate_news(_load_collection(connection, "news_items"))


def load_found_news():
    initialize_database()
    with _connect() as connection:
        return deduplicate_news(_load_collection(connection, "found_items"))


def find_news_by_url(url):
    """Находит одну публикацию без загрузки всей базы в веб-приложение."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT payload_json
            FROM news_items
            WHERE normalized_url = ?
            LIMIT 1
            """,
            (normalized,),
        ).fetchone()
    return _decode_item(row["payload_json"]) if row else None


def load_cached_article(url):
    """Возвращает сохранённый текст статьи, если её уже открывали."""
    normalized = normalize_url(url)
    if not normalized:
        return None
    initialize_database()
    with _connect() as connection:
        row = connection.execute(
            """
            SELECT source, title, paragraphs_json, fetched_at
            FROM article_cache
            WHERE normalized_url = ?
            """,
            (normalized,),
        ).fetchone()
    if row is None:
        return None
    try:
        paragraphs = json.loads(row["paragraphs_json"])
    except (TypeError, json.JSONDecodeError):
        logger.warning("В SQLite обнаружён повреждённый кеш статьи")
        return None
    if not isinstance(paragraphs, list) or not paragraphs:
        return None
    return {
        "title": row["title"],
        "paragraphs": paragraphs,
        "error": "",
        "source": row["source"],
        "cached": True,
        "cached_at": row["fetched_at"],
    }


def save_cached_article(url, article, source=""):
    """Сохраняет только успешный очищенный текст открытой статьи."""
    normalized = normalize_url(url)
    if not normalized or not isinstance(article, dict) or article.get("error"):
        return None
    paragraphs = _clean_cached_paragraphs(article.get("paragraphs", []))
    if not paragraphs:
        return None
    title = " ".join(str(article.get("title", "")).split())[:500]
    fetched_at = datetime.now().isoformat(timespec="seconds")
    initialize_database()
    with STORAGE_LOCK, _connect() as connection:
        connection.execute(
            """
            INSERT INTO article_cache(
                normalized_url, source, title, paragraphs_json, fetched_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(normalized_url) DO UPDATE SET
                source = excluded.source,
                title = excluded.title,
                paragraphs_json = excluded.paragraphs_json,
                fetched_at = excluded.fetched_at
            """,
            (
                normalized,
                str(source),
                title,
                json.dumps(paragraphs, ensure_ascii=False, separators=(",", ":")),
                fetched_at,
            ),
        )
    return load_cached_article(normalized)


def load_existing_urls():
    initialize_database()
    with _connect() as connection:
        rows = connection.execute(
            "SELECT normalized_url FROM news_items WHERE normalized_url != ''"
        ).fetchall()
    return {row["normalized_url"] for row in rows}


def save_results(all_news, found_news, existing_urls):
    with STORAGE_LOCK:
        return _save_results(all_news, found_news, existing_urls)


def _save_results(all_news, found_news, existing_urls):
    initialize_database()
    all_news = deduplicate_news(all_news)
    found_news = deduplicate_news(found_news)
    new_all = [
        item
        for item in all_news
        if normalize_url(item.get("url", "")) not in existing_urls
    ]
    new_found = [
        item
        for item in found_news
        if normalize_url(item.get("url", "")) not in existing_urls
    ]

    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    for item in new_all:
        if not item.get("parsed_date"):
            item["parsed_date"] = now
    for item in new_found:
        if not item.get("parsed_date"):
            item["parsed_date"] = now

    old_all = load_all_news()
    old_found = load_found_news()

    # Передаём все свежие записи, а не только новые: уже сохранённые
    # материалы смогут получить исправленную дату, ссылку или анонс.
    merged_all = merge_news(old_all, all_news)
    merged_found = merge_news(old_found, found_news)
    merged_all = _sort_items(merged_all)
    merged_found = _sort_items(merged_found)

    with _connect() as connection:
        _replace_collections(connection, merged_all, merged_found)

    print(f"✅ Новых: {len(new_all)} | Всего: {len(merged_all)}")
    print(
        f"🔴 Новых совпадений: {len(new_found)} | "
        f"Всего: {len(merged_found)}"
    )
    return new_found


def replace_found_news(items):
    """Полностью пересобирает таблицу совпадений после изменения слов."""
    with STORAGE_LOCK:
        initialize_database()
        all_news = load_all_news()
        found_news = deduplicate_news(items)
        available = {_news_key(item) for item in all_news}
        found_news = [
            item for item in found_news if _news_key(item) in available
        ]
        with _connect() as connection:
            connection.execute("DELETE FROM found_items")
            _insert_found_items(connection, found_news)
        return _sort_items(found_news)


def database_stats(connection=None):
    """Возвращает краткую статистику и результат проверки целостности."""
    owns_connection = connection is None
    if owns_connection:
        initialize_database()
        connection = _connect()
    try:
        news_count = connection.execute(
            "SELECT COUNT(*) FROM news_items"
        ).fetchone()[0]
        found_count = connection.execute(
            "SELECT COUNT(*) FROM found_items"
        ).fetchone()[0]
        cached_articles = connection.execute(
            "SELECT COUNT(*) FROM article_cache"
        ).fetchone()[0]
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        backups = _list_automatic_backups()
        migration = connection.execute(
            "SELECT value FROM metadata WHERE key = ?",
            (JSON_MIGRATION_KEY,),
        ).fetchone()
        return {
            "news_count": news_count,
            "found_count": found_count,
            "cached_articles": cached_articles,
            "integrity": integrity,
            "path": str(DATABASE_FILE),
            "size_bytes": (
                DATABASE_FILE.stat().st_size if DATABASE_FILE.exists() else 0
            ),
            "journal_mode": connection.execute(
                "PRAGMA journal_mode"
            ).fetchone()[0],
            "json_migrated": migration is not None,
            "backup_count": len(backups),
            "last_backup": str(backups[-1]) if backups else "",
        }
    finally:
        if owns_connection:
            connection.close()


def backup_database(destination=None):
    """Атомарно создаёт и проверяет копию работающей SQLite-базы."""
    initialize_database()
    destination = Path(destination or DATABASE_FILE.with_suffix(".backup.db"))
    if destination.resolve() == DATABASE_FILE.resolve():
        raise ValueError("резервная копия не может заменять рабочую базу")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.tmp")
    try:
        if temporary.exists():
            temporary.unlink()
        with STORAGE_LOCK:
            source = _connect()
            target = sqlite3.connect(temporary)
            try:
                source.backup(target)
                result = target.execute("PRAGMA integrity_check").fetchone()[0]
                if result != "ok":
                    raise sqlite3.DatabaseError(
                        f"проверка резервной копии завершилась: {result}"
                    )
            finally:
                # Контекстный менеджер sqlite3 завершает транзакцию, но не
                # закрывает соединение. На Windows открытый дескриптор не даёт
                # атомарно переименовать временную базу.
                target.close()
                source.close()
            os.replace(temporary, destination)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError as error:
                logger.warning(
                    f"Не удалось удалить временную копию SQLite: {error}"
                )
    return destination


def ensure_daily_backup(retention=7, now=None):
    """
    Создаёт не больше одной автоматической копии в день.

    Функцию безопасно вызывать после каждого цикла парсинга: если сегодняшний
    снимок уже существует, повторного копирования базы не будет.
    """
    initialize_database()
    moment = now or datetime.now()
    destination = BACKUP_DIR / (
        f"{DATABASE_FILE.stem}-{moment:%Y-%m-%d}.db"
    )
    created = False
    with STORAGE_LOCK:
        if not destination.exists():
            backup_database(destination)
            created = True
            logger.info(f"Создана резервная копия SQLite: {destination.name}")
        removed = _remove_old_backups(retention)
    return {
        "created": created,
        "path": str(destination),
        "removed": [str(path) for path in removed],
    }


def prepare_database(retention=7):
    """Проверяет рабочую базу и создаёт ежедневную резервную копию."""
    stats = database_stats()
    if stats["integrity"] != "ok":
        raise sqlite3.DatabaseError(
            f"проверка целостности SQLite завершилась: {stats['integrity']}"
        )
    backup = ensure_daily_backup(retention=retention)
    stats = database_stats()
    stats["backup_created"] = backup["created"]
    return stats


def _automatic_backup_pattern():
    return re.compile(
        rf"^{re.escape(DATABASE_FILE.stem)}-\d{{4}}-\d{{2}}-\d{{2}}\.db$"
    )


def _list_automatic_backups():
    if not BACKUP_DIR.exists():
        return []
    pattern = _automatic_backup_pattern()
    return sorted(
        path
        for path in BACKUP_DIR.iterdir()
        if path.is_file() and pattern.fullmatch(path.name)
    )


def _remove_old_backups(retention):
    try:
        retention = max(1, int(retention))
    except (TypeError, ValueError):
        retention = 7
    backups = _list_automatic_backups()
    removed = []
    for path in backups[:-retention]:
        path.unlink()
        removed.append(path)
        logger.info(f"Удалена старая резервная копия SQLite: {path.name}")
    return removed


def _replace_collections(connection, all_news, found_news):
    """Заменяет обе коллекции в одной транзакции: либо всё, либо ничего."""
    connection.execute("DELETE FROM found_items")
    connection.execute("DELETE FROM news_items")
    _insert_news_items(connection, all_news)

    available = {_news_key(item) for item in all_news}
    safe_found = [item for item in found_news if _news_key(item) in available]
    _insert_found_items(connection, safe_found)


def _insert_news_items(connection, items):
    updated_at = datetime.now().isoformat(timespec="seconds")
    rows = []
    for item in deduplicate_news(items):
        rows.append(
            (
                _news_key(item),
                normalize_url(item.get("url", "")),
                str(item.get("source", "")),
                str(item.get("title", "")),
                str(item.get("date", "")),
                str(item.get("parsed_date", "")),
                _encode_item(item),
                updated_at,
            )
        )
    connection.executemany(
        """
        INSERT INTO news_items(
            news_key, normalized_url, source, title,
            publication_date, parsed_date, payload_json, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )


def _insert_found_items(connection, items):
    updated_at = datetime.now().isoformat(timespec="seconds")
    connection.executemany(
        """
        INSERT INTO found_items(news_key, payload_json, updated_at)
        VALUES (?, ?, ?)
        """,
        [
            (_news_key(item), _encode_item(item), updated_at)
            for item in deduplicate_news(items)
        ],
    )


def _load_collection(connection, table):
    if table not in {"news_items", "found_items"}:
        raise ValueError("неизвестная таблица новостей")
    rows = connection.execute(
        f"SELECT payload_json FROM {table}"
    ).fetchall()
    return _sort_items(
        item
        for item in (_decode_item(row["payload_json"]) for row in rows)
        if item is not None
    )


def _encode_item(item):
    return json.dumps(dict(item), ensure_ascii=False, separators=(",", ":"))


def _decode_item(payload):
    try:
        item = json.loads(payload)
        return item if isinstance(item, dict) else None
    except (TypeError, json.JSONDecodeError):
        logger.warning("В SQLite обнаружена повреждённая запись новости")
        return None


def _clean_cached_paragraphs(paragraphs):
    if not isinstance(paragraphs, (list, tuple)):
        return []
    result = []
    seen = set()
    remaining = MAX_CACHED_ARTICLE_CHARS
    for paragraph in paragraphs:
        text = " ".join(str(paragraph or "").split())
        if not text or text in seen or remaining <= 0:
            continue
        text = text[:remaining]
        result.append(text)
        seen.add(text)
        remaining -= len(text)
    return result


def _news_key(item):
    normalized = normalize_url(item.get("url", ""))
    if normalized:
        return f"url:{normalized}"
    source = " ".join(str(item.get("source", "")).casefold().split())
    title = re.sub(
        r"[^\wа-яё]+",
        " ",
        str(item.get("title", "")).casefold(),
        flags=re.IGNORECASE,
    )
    return f"title:{source}:{' '.join(title.split())}"


def _sort_items(items):
    return sorted(
        items,
        key=lambda item: (
            str(item.get("date", "")),
            str(item.get("parsed_date", "")),
        ),
        reverse=True,
    )
